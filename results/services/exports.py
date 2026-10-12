from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from common.parsing import open_workbook
from records.models import Enrollment
from results.models import ResultSheet
from results.services.compute import ordinal
from results.services.pdf import SafeFPDF
from schools.models import AssessmentComponent, LevelSubject


def broadsheet_workbook(school_class, term):
    subjects = [ls.subject for ls in LevelSubject.objects.filter(level=school_class.level).select_related("subject")]
    enrollments = Enrollment.objects.filter(school_class=school_class, term=term).select_related("student")
    book = Workbook()
    sheet = book.active
    sheet.title = "Broadsheet"
    headers = ["S/N", "Admission No", "Name"] + [s.name for s in subjects] + ["Total", "Average", "Position"]
    sheet.append(headers)
    header_fill = PatternFill("solid", fgColor="0B3D2E")
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True)
    for index, enrollment in enumerate(enrollments, start=1):
        result = (
            ResultSheet.objects.filter(enrollment=enrollment, term=term)
            .prefetch_related("subject_results__subject")
            .order_by("-version")
            .first()
        )
        row = [index, enrollment.student.admission_number, enrollment.student.full_name]
        by_subject = {}
        if result:
            by_subject = {sr.subject_id: sr.total for sr in result.subject_results.all()}
        for subject in subjects:
            value = by_subject.get(subject.id)
            row.append(float(value) if value is not None else "")
        row.extend(
            [
                float(result.total_score) if result and result.total_score is not None else "",
                float(result.average) if result and result.average is not None else "",
                ordinal(result.position_class) if result else "",
            ]
        )
        sheet.append(row)
    sheet.freeze_panes = "D2"
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


def broadsheet_pdf(school_class, term):
    subjects = [ls.subject for ls in LevelSubject.objects.filter(level=school_class.level)]
    enrollments = Enrollment.objects.filter(school_class=school_class, term=term).select_related("student")
    pdf = SafeFPDF(orientation="L", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"{school_class.school.name} · {school_class.name} broadsheet · {term}", ln=1)
    pdf.set_font("Helvetica", size=7)
    headers = ["Name"] + [s.name[:10] for s in subjects] + ["Tot", "Avg", "Pos"]
    width = 277 / max(len(headers), 1)
    pdf.set_fill_color(11, 61, 46)
    pdf.set_text_color(255, 255, 255)
    for header in headers:
        pdf.cell(width, 6, header, fill=True)
    pdf.ln()
    pdf.set_text_color(20, 20, 20)
    for enrollment in enrollments:
        result = ResultSheet.objects.filter(enrollment=enrollment, term=term).order_by("-version").first()
        by_subject = {}
        if result:
            by_subject = {sr.subject_id: sr.total for sr in result.subject_results.all()}
        values = [enrollment.student.full_name[:16]]
        for subject in subjects:
            value = by_subject.get(subject.id)
            values.append(str(value) if value is not None else "")
        values.extend(
            [
                str(result.total_score) if result and result.total_score is not None else "",
                str(result.average) if result and result.average is not None else "",
                ordinal(result.position_class) if result else "",
            ]
        )
        for value in values:
            pdf.cell(width, 5, value)
        pdf.ln()
    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer


def score_sheet_workbook(school_class, subject, term):
    components = list(AssessmentComponent.objects.filter(session=term.session))
    enrollments = Enrollment.objects.filter(school_class=school_class, term=term).select_related("student")
    from results.models import Score

    book = Workbook()
    sheet = book.active
    sheet.title = "Scores"
    headers = ["admission_number", "name"] + [c.name for c in components]
    sheet.append(headers)
    for enrollment in enrollments:
        row = [enrollment.student.admission_number, enrollment.student.full_name]
        for component in components:
            score = Score.objects.filter(enrollment=enrollment, subject=subject, component=component).first()
            if not score:
                row.append("")
            elif score.marker == Score.Marker.ABSENT:
                row.append("AB")
            elif score.marker == Score.Marker.EXEMPT:
                row.append("EX")
            else:
                row.append(float(score.value) if score.value is not None else "")
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


def import_score_sheet(school_class, subject, term, uploaded, user):
    from results.models import Score, SubjectSheet

    book = open_workbook(uploaded)
    sheet = book.active
    first_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
    headers = [str(value or "").strip() for value in first_row]
    components = {c.name: c for c in AssessmentComponent.objects.filter(session=term.session)}
    if "admission_number" not in headers:
        raise ValueError("The first row must include an admission_number column. Download the template.")
    enrollments = {
        e.student.admission_number.upper(): e
        for e in Enrollment.objects.filter(school_class=school_class, term=term).select_related("student")
    }
    errors = []
    saved = 0
    for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):
            continue
        data = dict(zip(headers, row))
        admission = str(data.get("admission_number") or "").strip()
        enrollment = enrollments.get(admission.upper())
        if not enrollment:
            errors.append({"row": index, "error": f"Unknown admission number {admission}"})
            continue
        for name, component in components.items():
            raw = data.get(name)
            if raw is None or str(raw).strip() == "":
                continue
            text = str(raw).strip().upper()
            marker = Score.Marker.SCORE
            value = None
            if text in {"AB", "ABSENT"}:
                marker = Score.Marker.ABSENT
            elif text in {"EX", "EXEMPT"}:
                marker = Score.Marker.EXEMPT
            else:
                try:
                    value = Decimal(text)
                    if not value.is_finite():
                        raise InvalidOperation
                except InvalidOperation:
                    errors.append({"row": index, "error": f"{name}: '{raw}' is not a number"})
                    continue
                if value < 0 or value > component.max_score:
                    errors.append({"row": index, "error": f"{name}: {value} exceeds {component.max_score}"})
                    continue
            Score.objects.update_or_create(
                enrollment=enrollment,
                subject=subject,
                component=component,
                defaults={"value": value, "marker": marker, "updated_by": user},
            )
            saved += 1
    SubjectSheet.objects.get_or_create(school_class=school_class, subject=subject, term=term)
    return {"saved": saved, "errors": errors}


def transcript_data(student):
    sheets = (
        ResultSheet.objects.filter(enrollment__student=student, state__in=["published", "archived"])
        .select_related("term", "term__session", "enrollment__school_class")
        .prefetch_related("subject_results__subject")
        .order_by("term__session__name", "term__id")
    )
    return {
        "student": student,
        "school": student.school,
        "sheets": list(sheets),
    }
