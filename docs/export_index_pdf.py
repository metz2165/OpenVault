#!/usr/bin/env python3
from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / 'index.html'
PDF_PATH = ROOT / 'index.pdf'

class SectionTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.current_page = None
        self.tag_stack = []
        self.pages = {}
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tag_stack.append(tag)
        if tag == 'section' and attrs.get('class', '').find('content-page') >= 0:
            self.capture = True
            self.current_page = attrs.get('data-page', 'page')
            self.pages.setdefault(self.current_page, [])
        if not self.capture:
            return
        if tag in {'h2', 'h3', 'h4'}:
            self._buffer.append('\n')
        if tag == 'li':
            self._buffer.append('• ')
        if tag == 'tr':
            self._buffer.append('\n')
        if tag == 'td' or tag == 'th':
            self._buffer.append(' | ')

    def handle_endtag(self, tag):
        if self.tag_stack:
            self.tag_stack.pop()
        if self.capture and tag == 'section':
            text = ''.join(self._buffer)
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = re.sub(r' +', ' ', text)
            self.pages[self.current_page].append(text.strip())
            self._buffer = []
            self.capture = False
            self.current_page = None
        elif self.capture and tag in {'p', 'li', 'h2', 'h3', 'h4', 'pre'}:
            self._buffer.append('\n')

    def handle_data(self, data):
        if self.capture:
            stripped = data.strip('\n')
            if stripped.strip():
                self._buffer.append(stripped)


def wrap_text(text, width=95):
    lines = []
    for para in text.split('\n'):
        para = para.rstrip()
        if not para:
            lines.append('')
            continue
        while len(para) > width:
            cut = para.rfind(' ', 0, width)
            if cut <= 0:
                cut = width
            lines.append(para[:cut].rstrip())
            para = para[cut:].lstrip()
        lines.append(para)
    return lines


def escape_pdf_text(text: str) -> str:
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def build_pdf(lines):
    page_w, page_h = 595, 842  # A4 points
    margin_x, margin_top, margin_bottom = 40, 50, 40
    line_h = 14
    max_lines = (page_h - margin_top - margin_bottom) // line_h

    pages = [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)] or [[]]

    objects = []

    def add_obj(content: bytes):
        objects.append(content)
        return len(objects)

    font_obj = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    content_ids = []
    page_ids = []

    for page_lines in pages:
        y = page_h - margin_top
        stream = [b"BT", b"/F1 10 Tf", f"{margin_x} {y} Td".encode()]
        first = True
        for line in page_lines:
            if not first:
                stream.append(f"0 -{line_h} Td".encode())
            first = False
            stream.append(f"({escape_pdf_text(line)}) Tj".encode('latin-1', errors='replace'))
        stream.append(b"ET")
        data = b"\n".join(stream)
        content_id = add_obj(b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream")
        content_ids.append(content_id)

        page_obj = add_obj(
            b"<< /Type /Page /Parent PAGESREF /MediaBox [0 0 595 842] /Resources << /Font << /F1 "
            + str(font_obj).encode()
            + b" 0 R >> >> /Contents "
            + str(content_id).encode()
            + b" 0 R >>"
        )
        page_ids.append(page_obj)

    kids = b" ".join(str(pid).encode() + b" 0 R" for pid in page_ids)
    pages_obj = add_obj(b"<< /Type /Pages /Kids [ " + kids + b" ] /Count " + str(len(page_ids)).encode() + b" >>")

    for pid in page_ids:
        objects[pid - 1] = objects[pid - 1].replace(b"PAGESREF", str(pages_obj).encode() + b" 0 R")

    catalog_obj = add_obj(b"<< /Type /Catalog /Pages " + str(pages_obj).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())

    out.extend(
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root "
        + str(catalog_obj).encode()
        + b" 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


html = HTML_PATH.read_text(encoding='utf-8')
parser = SectionTextParser()
parser.feed(html)

ordered_pages = [('overview', 'OpenVault'), ('vault', 'Obsidian'), ('project', 'Folders')]
all_lines = ["OpenVault Documentation (Combined Pages)", ""]
for key, title in ordered_pages:
    chunks = parser.pages.get(key, [])
    if not chunks:
        continue
    all_lines.append(f"=== {title} ===")
    all_lines.append("")
    page_text = "\n\n".join(chunks)
    all_lines.extend(wrap_text(page_text))
    all_lines.append("")

PDF_PATH.write_bytes(build_pdf(all_lines))
print(f"Wrote {PDF_PATH}")
