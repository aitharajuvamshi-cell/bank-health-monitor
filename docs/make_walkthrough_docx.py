"""
Convert docs/WALKTHROUGH.md into a Word document (docs/Bank_Health_Monitor_Walkthrough.docx).
Handles the Markdown this guide uses: headings, paragraphs, bullets, numbered and
checkbox lists, tables, code blocks, **bold** and `code`.
"""
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

HERE = Path(__file__).resolve().parent
md = (HERE / "WALKTHROUGH.md").read_text(encoding="utf-8").splitlines()

doc = Document()
sec = doc.sections[0]
sec.left_margin = sec.right_margin = Cm(2.0)
sec.top_margin = sec.bottom_margin = Cm(1.8)
base = doc.styles["Normal"]
base.font.name = "Calibri"
base.font.size = Pt(10.5)
ACCENT = RGBColor(0x1C, 0x5C, 0xAB)
for lvl, size in ((1, 20), (2, 14), (3, 12)):
    st = doc.styles[f"Heading {lvl}"]
    st.font.name = "Calibri"
    st.font.size = Pt(size)
    st.font.color.rgb = ACCENT if lvl < 3 else RGBColor(0x22, 0x22, 0x22)


def add_inline(par, text):
    """**bold** and `code` inside a line."""
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**"):
            r = par.add_run(part[2:-2]); r.bold = True
        elif part.startswith("`"):
            r = par.add_run(part[1:-1]); r.font.name = "Consolas"; r.font.size = Pt(9.5)
        else:
            par.add_run(part)


def shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hex_fill)
    tcPr.append(sh)


i = 0
while i < len(md):
    line = md[i]
    if line.startswith("```"):
        block = []
        i += 1
        while i < len(md) and not md[i].startswith("```"):
            block.append(md[i]); i += 1
        p = doc.add_paragraph()
        r = p.add_run("\n".join(block)); r.font.name = "Consolas"; r.font.size = Pt(9)
        i += 1
        continue
    if line.startswith("|"):
        rows = []
        while i < len(md) and md[i].startswith("|"):
            cells = [c.strip() for c in md[i].strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                rows.append(cells)
            i += 1
        t = doc.add_table(rows=len(rows), cols=len(rows[0]))
        t.style = "Table Grid"
        for ri, row in enumerate(rows):
            for ci, val in enumerate(row):
                cell = t.cell(ri, ci)
                cell.text = ""
                add_inline(cell.paragraphs[0], val)
                for r in cell.paragraphs[0].runs:
                    r.font.size = Pt(9)
                    if ri == 0:
                        r.bold = True
                if ri == 0:
                    shade(cell, "E6EEFA")
        doc.add_paragraph()
        continue
    m = re.match(r"^(#{1,3}) (.*)", line)
    if m:
        doc.add_heading(m.group(2), level=len(m.group(1)))
    elif re.match(r"^- \[ \] ", line):
        p = doc.add_paragraph(style="List Bullet"); add_inline(p, "☐ " + line[6:])
    elif line.startswith("- "):
        p = doc.add_paragraph(style="List Bullet"); add_inline(p, line[2:])
    elif re.match(r"^\s{2,}- ", line):
        p = doc.add_paragraph(style="List Bullet 2"); add_inline(p, line.strip()[2:])
    elif re.match(r"^\d+\. ", line):
        p = doc.add_paragraph(style="List Number"); add_inline(p, re.sub(r"^\d+\. ", "", line))
    elif line.strip():
        p = doc.add_paragraph(); add_inline(p, line)
    i += 1

doc.core_properties.author = ""
doc.core_properties.title = "US Bank Health Monitor walkthrough"
out = HERE / "Bank_Health_Monitor_Walkthrough.docx"
doc.save(out)
print(f"wrote {out.name}")
