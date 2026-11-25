"""Export utilities for converting Markdown research dossiers into formatted Microsoft Word (.docx) and PDF documents."""
import io
import re
from typing import List, Tuple
from xml.sax.saxutils import escape as xml_escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _strip_html_comments_and_emojis(text: str) -> str:
    """Clean HTML comments and normalize decorative emojis for formal document exports."""
    cleaned = re.sub(r"<!--[\s\S]*?-->", "", text).strip()
    # Keep printable ASCII + common Unicode punctuation/math; strip emoji symbols that lack PDF font glyphs
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", cleaned)
    cleaned = re.sub(r"[\u2600-\u27bf]", "", cleaned)
    return cleaned


def _add_inline_markdown_runs(paragraph, text: str) -> None:
    """Parse basic inline **bold**, `code`, and [label](url) markdown into python-docx runs."""
    # Convert [label](url) links cleanly into "label (url)" or bold citation markers
    token_pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^\)]+\))")
    pos = 0
    for m in token_pattern.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        tok = m.group(0)
        if tok.startswith("**") and tok.endswith("**"):
            r = paragraph.add_run(tok[2:-2])
            r.bold = True
        elif tok.startswith("`") and tok.endswith("`"):
            r = paragraph.add_run(tok[1:-1])
            r.font.name = "Consolas"
            r.font.size = Pt(9.5)
        elif tok.startswith("["):
            link_m = re.match(r"^\[([^\]]+)\]\(([^\)]+)\)$", tok)
            if link_m:
                label, url = link_m.group(1), link_m.group(2)
                if label.strip() == url.strip():
                    r = paragraph.add_run(url)
                    r.font.color.rgb = RGBColor(0x02, 0x84, 0xC7)
                else:
                    r1 = paragraph.add_run(label)
                    r1.font.color.rgb = RGBColor(0x02, 0x84, 0xC7)
                    r2 = paragraph.add_run(f" ({url})")
                    r2.font.size = Pt(9)
                    r2.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
            else:
                paragraph.add_run(tok)
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def _parse_markdown_table(lines: List[str], start_idx: int) -> Tuple[List[List[str]], int]:
    """Parse contiguous Markdown table lines starting at start_idx."""
    rows: List[List[str]] = []
    idx = start_idx
    while idx < len(lines) and lines[idx].strip().startswith("|"):
        raw_line = lines[idx].strip()
        # Skip separator rows like |---|---|
        if re.match(r"^\|[\s\-:|]+\|$", raw_line):
            idx += 1
            continue
        cells = [c.strip() for c in raw_line.strip("|").split("|")]
        rows.append(cells)
        idx += 1
    return rows, idx


def _clean_cell_text(cell: str) -> str:
    """Flatten markdown syntax in table cells into clean readable text."""
    s = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1 (\2)", cell)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s.strip()


def markdown_to_docx_bytes(markdown_text: str, title: str = "Research Report") -> bytes:
    """Convert Markdown report into a cleanly styled Microsoft Word (.docx) byte stream."""
    doc = Document()

    # Configure standard page margins & typography
    for section in doc.sections:
        section.top_margin = Inches(0.85)
        section.bottom_margin = Inches(0.85)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Calibri"
    normal_style.font.size = Pt(11)
    normal_style.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)

    cleaned_md = _strip_html_comments_and_emojis(markdown_text)
    lines = cleaned_md.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Tables
        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            table_rows, next_i = _parse_markdown_table(lines, i)
            if table_rows:
                num_cols = max(len(r) for r in table_rows)
                tbl = doc.add_table(rows=len(table_rows), cols=num_cols)
                tbl.style = "Table Grid"
                for r_idx, row_vals in enumerate(table_rows):
                    for c_idx in range(num_cols):
                        val = _clean_cell_text(row_vals[c_idx]) if c_idx < len(row_vals) else ""
                        cell = tbl.cell(r_idx, c_idx)
                        p = cell.paragraphs[0]
                        p.paragraph_format.space_before = Pt(3)
                        p.paragraph_format.space_after = Pt(3)
                        run = p.add_run(val)
                        run.font.size = Pt(9.5)
                        if r_idx == 0:
                            run.bold = True
                            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                            shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="0F172A"/>')
                            cell._tc.get_or_add_tcPr().append(shading)
                doc.add_paragraph("")
            i = next_i
            continue

        # Headings
        if stripped.startswith("# "):
            h = doc.add_heading(stripped[2:].strip(), level=0)
            for r in h.runs:
                r.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
        elif stripped.startswith("## "):
            h = doc.add_heading(stripped[3:].strip(), level=1)
            for r in h.runs:
                r.font.color.rgb = RGBColor(0x03, 0x69, 0xA1)
        elif stripped.startswith("### "):
            h = doc.add_heading(stripped[4:].strip(), level=2)
            for r in h.runs:
                r.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)
        elif stripped.startswith("> "):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.space_after = Pt(4)
            _add_inline_markdown_runs(p, stripped[2:].strip())
            for r in p.runs:
                r.italic = True
                r.font.color.rgb = RGBColor(0x47, 0x55, 0x69)
        elif re.match(r"^[-*•]\s+", stripped):
            item_text = re.sub(r"^[-*•]\s+", "", stripped)
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(3)
            _add_inline_markdown_runs(p, item_text)
        elif re.match(r"^\d+\.\s+", stripped):
            item_text = re.sub(r"^\d+\.\s+", "", stripped)
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_after = Pt(3)
            _add_inline_markdown_runs(p, item_text)
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            _add_inline_markdown_runs(p, stripped)

        i += 1

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def _md_to_reportlab_html(text: str) -> str:
    """Convert basic inline Markdown to safe ReportLab Paragraph markup."""
    escaped = xml_escape(text)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<font name='Courier' size='9'>\1</font>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"<font color='#0284c7'>\1</font>", escaped)
    return escaped


def markdown_to_pdf_bytes(markdown_text: str, title: str = "Research Report") -> bytes:
    """Convert Markdown research report into a crisp, readable PDF byte stream using ReportLab."""
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=title,
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=10,
        alignment=0,
    )
    style_h2 = ParagraphStyle(
        "DocH2",
        parent=styles["Heading2"],
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#0369a1"),
        spaceBefore=12,
        spaceAfter=6,
    )
    style_h3 = ParagraphStyle(
        "DocH3",
        parent=styles["Heading3"],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=8,
        spaceAfter=4,
    )
    style_body = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14.5,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=6,
    )
    style_bullet = ParagraphStyle(
        "DocBullet",
        parent=style_body,
        leftIndent=14,
        firstLineIndent=-8,
        spaceAfter=4,
    )
    style_quote = ParagraphStyle(
        "DocQuote",
        parent=style_body,
        leftIndent=12,
        textColor=colors.HexColor("#475569"),
        fontSize=9.5,
    )
    style_cell = ParagraphStyle(
        "CellBody",
        parent=style_body,
        fontSize=8.5,
        leading=11.5,
        spaceAfter=0,
    )
    style_cell_hdr = ParagraphStyle(
        "CellHeader",
        parent=style_cell,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    story = []
    cleaned_md = _strip_html_comments_and_emojis(markdown_text)
    lines = cleaned_md.splitlines()

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            table_rows, next_i = _parse_markdown_table(lines, i)
            if table_rows:
                num_cols = max(len(r) for r in table_rows)
                avail_w = 7.0 * inch
                if num_cols == 3:
                    col_widths = [0.45 * inch, 4.45 * inch, 2.1 * inch]
                else:
                    col_widths = [avail_w / num_cols] * num_cols

                rl_rows = []
                for r_idx, row_vals in enumerate(table_rows):
                    c_style = style_cell_hdr if r_idx == 0 else style_cell
                    rl_row = []
                    for c_idx in range(num_cols):
                        txt = _clean_cell_text(row_vals[c_idx]) if c_idx < len(row_vals) else ""
                        rl_row.append(Paragraph(xml_escape(txt), c_style))
                    rl_rows.append(rl_row)

                tbl = Table(rl_rows, colWidths=col_widths, repeatRows=1)
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]))
                story.append(tbl)
                story.append(Spacer(1, 8))
            i = next_i
            continue

        if stripped.startswith("# "):
            story.append(Paragraph(_md_to_reportlab_html(stripped[2:].strip()), style_title))
        elif stripped.startswith("## "):
            story.append(Paragraph(_md_to_reportlab_html(stripped[3:].strip()), style_h2))
        elif stripped.startswith("### "):
            story.append(Paragraph(_md_to_reportlab_html(stripped[4:].strip()), style_h3))
        elif stripped.startswith("> "):
            story.append(Paragraph(_md_to_reportlab_html(stripped[2:].strip()), style_quote))
        elif re.match(r"^[-*•]\s+", stripped):
            item_text = re.sub(r"^[-*•]\s+", "", stripped)
            story.append(Paragraph(f"&bull; {_md_to_reportlab_html(item_text)}", style_bullet))
        elif re.match(r"^\d+\.\s+", stripped):
            story.append(Paragraph(_md_to_reportlab_html(stripped), style_bullet))
        else:
            story.append(Paragraph(_md_to_reportlab_html(stripped), style_body))

        i += 1

    if not story:
        story.append(Paragraph(xml_escape(title), style_title))

    pdf.build(story)
    buf.seek(0)
    return buf.read()
