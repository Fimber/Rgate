import re
from io import BytesIO

from django.core.files.base import ContentFile
from fpdf import FPDF, XPos, YPos

CHAR_FALLBACKS = {"₦": "N", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "..."}


def latin_safe(text, encoding="latin-1"):
    """Fit text into a core PDF font without crashing on names like Ọlábísí or Ẹ̀mẹ́kà.

    Characters the font can draw are kept; others lose their combining marks
    (Ọ -> O) and anything still unprintable becomes '?'.
    """
    import unicodedata

    out = []
    for char in str(text):
        try:
            char.encode(encoding)
            out.append(char)
            continue
        except UnicodeEncodeError:
            pass
        if char in CHAR_FALLBACKS:
            out.append(CHAR_FALLBACKS[char])
            continue
        base = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
        try:
            base.encode(encoding)
            out.append(base)
        except UnicodeEncodeError:
            out.append("?")
    return unicodedata.normalize("NFC", "".join(out))


class SafeFPDF(FPDF):
    def multi_cell(self, w, h=None, text="", *args, **kwargs):
        # fpdf2 >= 2.5 leaves the cursor at the right margin after a multi_cell, so the
        # next full-width cell would have zero width and raise. Return to the left margin.
        if not args:
            kwargs.setdefault("new_x", XPos.LMARGIN)
            kwargs.setdefault("new_y", YPos.NEXT)
        return super().multi_cell(w, h, text, *args, **kwargs)

    def normalize_text(self, text):
        if not self.is_ttf_font and self.core_fonts_encoding:
            text = latin_safe(text, self.core_fonts_encoding)
        return super().normalize_text(text)


class ResultPDF(SafeFPDF):
    def __init__(self, colour="#0B3D2E"):
        super().__init__(format="A4")
        self.colour = _hex_rgb(colour)
        self.set_auto_page_break(auto=True, margin=12)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", size=7)
        self.set_text_color(90, 90, 90)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="C")


def verify_url(sheet):
    from django.conf import settings

    return f"{settings.PLATFORM_DOMAIN}/{sheet.school.slug}/verify/{sheet.result_code}/"


def _hex_rgb(value):
    value = (value or "#0B3D2E").lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        value = "0B3D2E"
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


# How each result card template differs on paper. Keep in step with the .tpl-* CSS classes.
CARD_STYLES = {
    "classic": {"header": "classic", "base": 8, "row": 5.5, "remark": True, "avg": True, "zebra": False, "lines": True},
    "compact": {
        "header": "compact",
        "base": 7,
        "row": 4.4,
        "remark": False,
        "avg": False,
        "zebra": False,
        "lines": False,
    },
    "colour": {"header": "band", "base": 8, "row": 5.5, "remark": True, "avg": True, "zebra": True, "lines": False},
}


def _fit(pdf, text, width):
    """Trim text to the cell width with an ellipsis, measured in the current font."""
    text = str(text)
    room = width - 1.5
    if pdf.get_string_width(text) <= room:
        return text
    while text and pdf.get_string_width(text + "...") > room:
        text = text[:-1]
    return text.rstrip() + "..."


def _tint(rgb, strength=0.12):
    return tuple(int(255 - (255 - c) * strength) for c in rgb)


def _header(pdf, style, school, term, rgb):
    r, g, b = rgb
    title = f"{term.get('name', '')} Term Result  ·  {term.get('session', '')}"
    contact = "  ·  ".join(x for x in (school.get("phone", ""), school.get("email", "")) if x)
    if style == "band":
        pdf.set_fill_color(r, g, b)
        pdf.rect(0, 0, 210, 30, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(12, 6)
        pdf.cell(0, 8, school.get("name", "School"))
        pdf.set_font("Helvetica", size=8)
        pdf.set_xy(12, 14)
        pdf.cell(0, 5, school.get("address", ""))
        pdf.set_xy(12, 19)
        pdf.cell(0, 5, contact)
        pdf.set_text_color(20, 20, 20)
        pdf.set_y(35)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, title.upper(), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    elif style == "classic":
        pdf.set_y(10)
        pdf.set_text_color(r, g, b)
        pdf.set_font("Times", "B", 18)
        pdf.cell(0, 9, school.get("name", "School").upper(), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(70, 70, 70)
        if school.get("motto"):
            pdf.set_font("Times", "I", 9)
            pdf.cell(0, 5, school["motto"], align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", size=8)
        pdf.cell(0, 4.5, school.get("address", ""), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 4.5, contact, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_draw_color(r, g, b)
        y = pdf.get_y() + 2
        pdf.set_line_width(0.8)
        pdf.line(12, y, 198, y)
        pdf.set_line_width(0.2)
        pdf.line(12, y + 1.2, 198, y + 1.2)
        pdf.set_y(y + 4)
        pdf.set_text_color(20, 20, 20)
        pdf.set_font("Times", "B", 12)
        pdf.cell(0, 7, title.upper(), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:  # compact
        pdf.set_y(9)
        pdf.set_text_color(r, g, b)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(110, 6, school.get("name", "School"))
        pdf.set_text_color(90, 90, 90)
        pdf.set_font("Helvetica", size=7)
        pdf.cell(0, 6, title, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(
            0,
            4,
            "  ·  ".join(x for x in (school.get("address", ""), contact) if x),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.set_draw_color(r, g, b)
        pdf.set_line_width(0.4)
        pdf.line(12, pdf.get_y() + 1, 198, pdf.get_y() + 1)
        pdf.set_line_width(0.2)
        pdf.set_y(pdf.get_y() + 3)
        pdf.set_text_color(20, 20, 20)


def build_result_pdf(data, result_code, verify, template="classic", show_positions=True):
    """Render a result snapshot to PDF bytes. Pure: no database, so examples can use it too."""
    style = CARD_STYLES.get(template, CARD_STYLES["classic"])
    school = data.get("school", {})
    student = data.get("student", {})
    term = data.get("term", {})
    summary = data.get("summary", {})
    pdf = ResultPDF(school.get("brand_colour") or "#0B3D2E")
    pdf.alias_nb_pages()
    pdf.add_page()
    rgb = pdf.colour
    r, g, b = rgb
    base = style["base"]
    _header(pdf, style["header"], school, term, rgb)

    pdf.set_font("Helvetica", "B" if style["header"] != "compact" else "", base + 1)
    who = f"{student.get('name', '')}  ·  {student.get('admission_number', '')}  ·  {student.get('class', '')}"
    if student.get("sex"):
        who += f"  ·  {student['sex']}"
    pdf.cell(0, 5.5, who, align="L" if style["header"] == "compact" else "C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.5)

    subjects = data.get("subjects", [])
    component_keys = list(subjects[0].get("components", {}).keys()) if subjects else []
    pdf.set_font("Helvetica", "B", base - 1)
    # Component columns grow to fit their heading ("Assignment"), the subject column takes the rest.
    columns = [("Subject", 38, "name")] + [(k, max(12, pdf.get_string_width(k) + 3), None) for k in component_keys]
    columns += [("Total", 12, "total"), ("Grade", 12, "grade")]
    if style["remark"]:
        columns.append(("Remark", 30, "remark"))
    if show_positions:
        columns.append(("Pos", 12, "position"))
    if style["avg"]:
        columns.append(("Cl. avg", 14, "class_average"))
    widths = [w for _, w, _ in columns]
    widths[0] += 186 - sum(widths)

    pdf.set_font("Helvetica", "B", base - 1)
    if style["header"] == "band":
        pdf.set_fill_color(r, g, b)
        pdf.set_text_color(255, 255, 255)
        fill_head, border_head = True, 0
    elif style["header"] == "classic":
        pdf.set_fill_color(236, 236, 232)
        fill_head, border_head = True, "TB"
    else:
        fill_head, border_head = False, "B"
    pdf.set_draw_color(r, g, b) if style["header"] == "compact" else pdf.set_draw_color(150, 150, 150)
    for (label, _, _), width in zip(columns, widths):
        pdf.cell(width, style["row"] + 0.5, _fit(pdf, label, width), border=border_head, fill=fill_head)
    pdf.ln()
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", size=base - 1)
    pdf.set_draw_color(215, 215, 210)
    zebra = _tint(rgb)
    for index, row in enumerate(subjects):
        fill = style["zebra"] and index % 2 == 0
        pdf.set_fill_color(*zebra)
        for (label, _, field), width in zip(columns, widths):
            value = row.get(field, "") if field else row.get("components", {}).get(label, "")
            pdf.cell(width, style["row"], _fit(pdf, value, width), border="B" if style["lines"] else 0, fill=fill)
        pdf.ln()

    pdf.ln(2)
    facts = [f"Total: {summary.get('total') or '—'}", f"Average: {summary.get('average') or '—'}%"]
    if show_positions:
        facts.append(f"Position: {summary.get('position', '—')} of {summary.get('class_size') or '—'}")
    facts += [
        f"Subjects: {summary.get('subjects_offered', '—')}",
        f"Cumulative: {summary.get('cumulative_average') or '—'}",
        f"Attendance: {summary.get('days_present') or '—'} / {term.get('days_opened') or '—'}",
        f"Promotion: {summary.get('promotion', '—')}",
    ]
    pdf.set_font("Helvetica", "B", base + 1)
    pdf.cell(0, 6, "Summary", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=base)
    pdf.multi_cell(0, 5, "    ".join(facts))

    ratings = data.get("ratings") or {}
    if ratings:
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", base + 1)
        pdf.cell(0, 6, "Behavioural ratings (1-5)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", size=base)
        pdf.multi_cell(0, 4.5, "    ".join(f"{name}: {value}" for name, value in ratings.items()))
    comments = data.get("comments") or {}
    for role, label in (("class_teacher", "Class teacher"), ("head_of_school", "Head of school")):
        if comments.get(role):
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", base + 1)
            pdf.cell(0, 5, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("Helvetica", "I", base)
            pdf.multi_cell(0, 4.5, comments[role])
    if term.get("resumption"):
        pdf.set_font("Helvetica", size=base)
        pdf.cell(0, 5, f"Next term resumes: {term['resumption']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    key = data.get("grading_key") or []
    if key:
        pdf.set_font("Helvetica", size=base - 1)
        pdf.multi_cell(0, 4, "Grading: " + "  ".join(f"{k['label']} {k['range']} {k['remark']}" for k in key))
    pdf.ln(2)
    pdf.set_draw_color(r, g, b)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", size=7)
    pdf.multi_cell(
        0, 4, f"Result ID {result_code}  ·  Verify at {verify}  ·  A published result is never silently edited."
    )
    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def generate_result_pdf(sheet):
    """Build and store the sheet's PDF using the school's current template and position rule."""
    school = sheet.school
    content = build_result_pdf(
        sheet.snapshot or {},
        sheet.result_code,
        verify_url(sheet),
        template=school.result_template,
        show_positions=school.show_positions,
    )
    sheet.pdf_file.save(f"{sheet.result_code}.pdf", ContentFile(content), save=True)
    return sheet.pdf_file
