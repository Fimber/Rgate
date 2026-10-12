from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.parsing import to_int
from common.tenancy import school_staff_required
from records.models import ClassTeacherAssignment, Enrollment, SubjectAssignment
from results.models import (
    BehaviouralRating,
    ClassCycle,
    Comment,
    CommentBank,
    ResultSheet,
    Score,
    SubjectSheet,
)
from results.services.cards import card_options
from results.services.compute import recompute_class
from results.services.exports import (
    broadsheet_pdf,
    broadsheet_workbook,
    import_score_sheet,
    score_sheet_workbook,
    transcript_data,
)
from results.services.workflow import (
    approve_class,
    get_cycle,
    publish_classes,
    review_class,
    submit_sheet,
    unlock_sheet,
)
from schools.models import AssessmentComponent, BehaviouralTrait, LevelSubject, SchoolClass

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _assignment_for(request, assignment_id):
    """The assignment, if it belongs to this school and this user may mark it."""
    assignment = get_object_or_404(
        SubjectAssignment.objects.select_related("school_class", "subject", "term__session"),
        pk=assignment_id,
        school_class__school=request.school,
    )
    if not request.user.is_school_admin_like and assignment.teacher_id != request.user.id:
        raise PermissionDenied("This subject is assigned to another teacher.")
    return assignment


def _sheet_for(assignment):
    sheet, _ = SubjectSheet.objects.get_or_create(
        school_class=assignment.school_class, subject=assignment.subject, term=assignment.term
    )
    return sheet


def _can_review(user, school_class, term):
    if user.is_school_admin_like:
        return True
    return ClassTeacherAssignment.objects.filter(teacher=user, school_class=school_class, term=term).exists()


def _assigned_sheets(user, term):
    if user.is_school_admin_like:
        return SubjectAssignment.objects.filter(term=term)
    return SubjectAssignment.objects.filter(term=term, teacher=user)


@school_staff_required
def score_home(request):
    school = request.school
    term = school.current_term()
    assignments = _assigned_sheets(request.user, term) if term else SubjectAssignment.objects.none()
    assignments = list(assignments.select_related("school_class", "subject"))
    rows = []
    if assignments:
        class_sizes, filled = _class_progress(term)
        sheets = {
            (s.school_class_id, s.subject_id): s
            for s in SubjectSheet.objects.filter(term=term, school_class__school=school)
        }
        for assignment in assignments:
            key = (assignment.school_class_id, assignment.subject_id)
            sheet = sheets.get(key) or _sheet_for(assignment)
            rows.append(
                {
                    "assignment": assignment,
                    "sheet": sheet,
                    "enrollments": class_sizes.get(assignment.school_class_id, 0),
                    "filled": filled.get(key, 0),
                }
            )
    return render(request, "results/score_home.html", {"rows": rows, "term": term})


def _class_progress(term):
    """Two aggregate queries: enrolled per class, and students with any score per (class, subject)."""
    class_sizes = dict(
        Enrollment.objects.filter(term=term)
        .values("school_class")
        .annotate(n=Count("id"))
        .values_list("school_class", "n")
    )
    filled = {
        (row["enrollment__school_class"], row["subject"]): row["n"]
        for row in Score.objects.filter(enrollment__term=term)
        .values("enrollment__school_class", "subject")
        .annotate(n=Count("enrollment", distinct=True))
    }
    return class_sizes, filled


@school_staff_required
def score_entry(request, assignment_id):
    assignment = _assignment_for(request, assignment_id)
    term = assignment.term
    components = list(AssessmentComponent.objects.filter(session=term.session))
    sheet = _sheet_for(assignment)
    locked = sheet.state == SubjectSheet.State.SUBMITTED and not request.user.is_school_admin_like
    enrollments = list(
        Enrollment.objects.filter(school_class=assignment.school_class, term=term)
        .select_related("student")
        .order_by("student__surname", "student__first_name")
    )
    scores = Score.objects.filter(enrollment__in=enrollments, subject=assignment.subject, component__in=components)
    lookup = {(s.enrollment_id, s.component_id): s for s in scores}
    rows = []
    for enrollment in enrollments:
        cells = []
        for component in components:
            cells.append({"component": component, "score": lookup.get((enrollment.id, component.id))})
        rows.append({"enrollment": enrollment, "cells": cells})
    return render(
        request,
        "results/score_entry.html",
        {
            "assignment": assignment,
            "sheet": sheet,
            "components": components,
            "rows": rows,
            "locked": locked,
        },
    )


@school_staff_required
@require_POST
def score_save(request, assignment_id):
    assignment = _assignment_for(request, assignment_id)
    sheet = _sheet_for(assignment)
    if sheet.state == SubjectSheet.State.SUBMITTED and not request.user.is_school_admin_like:
        return JsonResponse({"ok": False, "error": "Sheet is locked"}, status=400)
    enrollment = get_object_or_404(
        Enrollment,
        pk=to_int(request.POST.get("enrollment")),
        school_class=assignment.school_class,
        term=assignment.term,
    )
    component = get_object_or_404(
        AssessmentComponent, pk=to_int(request.POST.get("component")), session=assignment.term.session
    )
    raw = (request.POST.get("value") or "").strip()
    marker = request.POST.get("marker") or Score.Marker.SCORE
    if marker not in Score.Marker.values:
        return JsonResponse({"ok": False, "error": "Unknown marker"}, status=400)
    value = None
    if marker == Score.Marker.SCORE:
        if raw == "":
            Score.objects.filter(enrollment=enrollment, subject=assignment.subject, component=component).delete()
            return JsonResponse({"ok": True, "saved": True, "synced": True, "cleared": True})
        try:
            value = Decimal(raw)
            if not value.is_finite():
                raise InvalidOperation
        except InvalidOperation:
            return JsonResponse({"ok": False, "error": "Enter a number"}, status=400)
        if value < 0 or value > component.max_score:
            return JsonResponse({"ok": False, "error": f"Maximum is {component.max_score}"}, status=400)
    Score.objects.update_or_create(
        enrollment=enrollment,
        subject=assignment.subject,
        component=component,
        defaults={"value": value, "marker": marker, "updated_by": request.user, "synced_at": timezone.now()},
    )
    return JsonResponse({"ok": True, "saved": True, "synced": True})


@school_staff_required
@require_POST
def score_submit(request, assignment_id):
    assignment = _assignment_for(request, assignment_id)
    sheet = _sheet_for(assignment)
    try:
        submit_sheet(request, sheet)
        messages.success(request, f"{assignment.subject} for {assignment.school_class} submitted.")
    except PermissionError as exc:
        messages.error(request, str(exc))
    return redirect("results:score_entry", assignment_id=assignment.id)


@school_staff_required
@require_POST
def score_unlock(request, assignment_id):
    assignment = _assignment_for(request, assignment_id)
    sheet = get_object_or_404(
        SubjectSheet, school_class=assignment.school_class, subject=assignment.subject, term=assignment.term
    )
    try:
        unlock_sheet(request, sheet)
        messages.success(request, "Sheet reopened.")
    except PermissionError as exc:
        messages.error(request, str(exc))
    return redirect("results:score_entry", assignment_id=assignment.id)


@school_staff_required
def score_excel(request, assignment_id):
    assignment = _assignment_for(request, assignment_id)
    if request.method == "POST" and request.FILES.get("file"):
        upload = request.FILES["file"]
        locked = _sheet_for(assignment).state == SubjectSheet.State.SUBMITTED
        if locked and not request.user.is_school_admin_like:
            messages.error(request, "This sheet is submitted. Ask an admin to reopen it before importing.")
        elif upload.size > MAX_UPLOAD_BYTES:
            messages.error(request, "That file is larger than 5 MB.")
        else:
            try:
                result = import_score_sheet(
                    assignment.school_class, assignment.subject, assignment.term, upload, request.user
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Saved {result['saved']} scores. {len(result['errors'])} row issues.")
                request.session["import_errors"] = result["errors"][:100]
        return redirect("results:score_entry", assignment_id=assignment.id)
    buffer = score_sheet_workbook(assignment.school_class, assignment.subject, assignment.term)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{assignment.school_class}-{assignment.subject}.xlsx"'
    return response


@school_staff_required
def progress(request):
    school = request.school
    term = school.current_term()
    rows = []
    if term:
        class_sizes, filled_map = _class_progress(term)
        level_subjects = {}
        for ls in LevelSubject.objects.filter(level__school=school).select_related("subject"):
            level_subjects.setdefault(ls.level_id, []).append(ls)
        sheets = {
            (s.school_class_id, s.subject_id): s
            for s in SubjectSheet.objects.filter(term=term, school_class__school=school)
        }
        cycles = {c.school_class_id: c for c in ClassCycle.objects.filter(term=term, school_class__school=school)}
        for school_class in school.classes.select_related("level"):
            subject_rows = []
            total = class_sizes.get(school_class.id, 0)
            for ls in level_subjects.get(school_class.level_id, []):
                sheet = sheets.get((school_class.id, ls.subject_id))
                filled = filled_map.get((school_class.id, ls.subject_id), 0)
                if sheet and sheet.state == SubjectSheet.State.SUBMITTED:
                    status = "complete"
                elif filled:
                    status = "partial"
                else:
                    status = "untouched"
                subject_rows.append({"subject": ls.subject, "status": status, "filled": filled, "total": total})
            cycle = cycles.get(school_class.id) or get_cycle(school_class, term)
            rows.append({"class": school_class, "subjects": subject_rows, "cycle": cycle})
    return render(request, "results/progress.html", {"rows": rows, "term": term})


@school_staff_required
def review(request, class_id):
    school_class = get_object_or_404(SchoolClass, pk=class_id, school=request.school)
    term = request.school.current_term()
    if term is None:
        messages.error(request, "Set the current term first.")
        return redirect("results:progress")
    if not _can_review(request.user, school_class, term):
        messages.error(request, "You are not the class teacher for this class.")
        return redirect("results:progress")
    recompute_class(school_class, term)
    enrollments = Enrollment.objects.filter(school_class=school_class, term=term).select_related("student")
    sheets = {
        s.enrollment_id: s
        for s in ResultSheet.objects.filter(enrollment__school_class=school_class, term=term)
        .prefetch_related("subject_results", "comments")
        .order_by("-version")
    }
    traits = request.school.traits.filter(
        domain__in=[
            BehaviouralTrait.Domain.AFFECTIVE,
            BehaviouralTrait.Domain.PSYCHOMOTOR,
            BehaviouralTrait.Domain.SKILL,
        ]
    )
    if school_class.level.report_type == "skills":
        traits = traits.filter(domain=BehaviouralTrait.Domain.SKILL)
    else:
        traits = traits.exclude(domain=BehaviouralTrait.Domain.SKILL)
    ratings = {
        (r.enrollment_id, r.trait_id): r.value
        for r in BehaviouralRating.objects.filter(enrollment__school_class=school_class, term=term)
    }
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_review":
            for enrollment in enrollments:
                sheet = sheets.get(enrollment.id)
                if not sheet:
                    continue
                present = to_int(request.POST.get(f"present_{enrollment.id}"), minimum=0, maximum=366)
                if present is not None:
                    sheet.days_present = present
                    sheet.save(update_fields=["days_present"])
                comment = (request.POST.get(f"ct_{enrollment.id}") or "").strip()
                if comment:
                    Comment.objects.update_or_create(
                        result_sheet=sheet,
                        author_role=Comment.AuthorRole.CLASS_TEACHER,
                        defaults={"body": comment, "author": request.user},
                    )
                for trait in traits:
                    rating = to_int(request.POST.get(f"trait_{enrollment.id}_{trait.id}"), minimum=1, maximum=5)
                    if rating is not None:
                        BehaviouralRating.objects.update_or_create(
                            enrollment=enrollment, term=term, trait=trait, defaults={"value": rating}
                        )
            messages.success(request, "Class review saved.")
        elif action == "review":
            try:
                cycle, incompletes = review_class(request, school_class, term)
                if incompletes:
                    messages.warning(
                        request,
                        f"Marked reviewed, but {incompletes.count()} result(s) are incomplete.",
                    )
                else:
                    messages.success(request, f"{school_class} sent to the head of school.")
            except ValueError as exc:
                messages.error(request, str(exc))
        elif action == "approve" and request.user.is_school_admin_like:
            for enrollment in enrollments:
                sheet = sheets.get(enrollment.id)
                if not sheet:
                    continue
                comment = (request.POST.get(f"hs_{enrollment.id}") or "").strip()
                if comment:
                    Comment.objects.update_or_create(
                        result_sheet=sheet,
                        author_role=Comment.AuthorRole.HEAD_OF_SCHOOL,
                        defaults={"body": comment, "author": request.user},
                    )
            try:
                approve_class(request, school_class, term)
                messages.success(request, f"{school_class} approved for publishing.")
            except ValueError as exc:
                messages.error(request, str(exc))
        return redirect("results:review", class_id=school_class.id)
    bank = CommentBank.objects.filter(school=request.school)
    enrollments = list(enrollments)
    trait_list = list(traits)
    for enrollment in enrollments:
        # Pre-pair each trait with its saved value so the form shows what was chosen last time.
        enrollment.trait_rows = [(trait, ratings.get((enrollment.id, trait.id))) for trait in trait_list]
    return render(
        request,
        "results/review.html",
        {
            "school_class": school_class,
            "term": term,
            "enrollments": enrollments,
            "sheets": sheets,
            "traits": traits,
            "ratings": ratings,
            "cycle": get_cycle(school_class, term),
            "bank": bank,
        },
    )


@school_staff_required
def publish(request):
    school = request.school
    term = school.current_term()
    classes = list(school.classes.select_related("level"))
    cycles = {c.school_class_id: c for c in (term.cycles.all() if term else [])}
    if request.method == "POST" and request.user.is_school_admin_like and term:
        scope = request.POST.get("scope")
        selected = []
        if scope == "school":
            selected = classes
        elif scope == "class":
            selected = [get_object_or_404(SchoolClass, pk=request.POST.get("school_class"), school=school)]
        try:
            published = publish_classes(request, term, selected, send_sms=request.POST.get("sms") == "on")
            from results.models import Publication

            Publication.objects.create(
                school=school,
                term=term,
                school_class=selected[0] if scope == "class" and selected else None,
                scope="school" if scope == "school" else "class",
                published_by=request.user,
            )
            messages.success(request, f"Published {len(published)} result(s).")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("results:publish")
    incompletes = (
        ResultSheet.objects.filter(enrollment__student__school=school, term=term, incomplete=True)
        .exclude(state="published")
        .select_related("enrollment__student", "enrollment__school_class")
        if term
        else []
    )
    return render(
        request,
        "results/publish.html",
        {"classes": classes, "cycles": cycles, "term": term, "incompletes": incompletes},
    )


@school_staff_required
def preview(request, sheet_id):
    sheet = get_object_or_404(ResultSheet, pk=sheet_id, enrollment__student__school=request.school)
    return render(
        request,
        "results/result_card.html",
        {"sheet": sheet, "data": sheet.snapshot or _live_card(sheet), **card_options(request.school)},
    )


def _live_card(sheet):
    from results.services.compute import snapshot_sheet

    if sheet.snapshot:
        return sheet.snapshot
    return snapshot_sheet(sheet)


@school_staff_required
def broadsheet(request, class_id):
    school_class = get_object_or_404(SchoolClass, pk=class_id, school=request.school)
    term = request.school.current_term()
    if term is None:
        messages.error(request, "Set the current term first.")
        return redirect("results:progress")
    recompute_class(school_class, term)
    fmt = request.GET.get("format")
    if fmt == "xlsx":
        buffer = broadsheet_workbook(school_class, term)
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{school_class}-broadsheet.xlsx"'
        return response
    if fmt == "pdf":
        buffer = broadsheet_pdf(school_class, term)
        return FileResponse(buffer, as_attachment=True, filename=f"{school_class}-broadsheet.pdf")
    enrollments = Enrollment.objects.filter(school_class=school_class, term=term).select_related("student")
    subjects = [ls.subject for ls in LevelSubject.objects.filter(level=school_class.level)]
    sheets = {
        s.enrollment_id: s
        for s in ResultSheet.objects.filter(enrollment__school_class=school_class, term=term).prefetch_related(
            "subject_results"
        )
    }
    return render(
        request,
        "results/broadsheet.html",
        {
            "school_class": school_class,
            "term": term,
            "enrollments": enrollments,
            "subjects": subjects,
            "sheets": sheets,
        },
    )


@school_staff_required
def transcripts(request):
    query = (request.GET.get("q") or "").strip()
    students = request.school.students.all()
    if query:
        students = students.filter(surname__icontains=query) | request.school.students.filter(
            admission_number__icontains=query
        )
    return render(request, "results/transcripts.html", {"students": students[:80], "query": query})


@school_staff_required
def transcript_detail(request, student_id):
    from records.models import Student

    student = get_object_or_404(Student, pk=student_id, school=request.school)
    return render(request, "results/transcript.html", transcript_data(student))


def verify_result(request, code):
    """Public check that a printed result is genuine, scoped to the school in the URL."""
    sheets = ResultSheet.objects.filter(result_code__iexact=code, state__in=["published", "archived"])
    if getattr(request, "school", None):
        sheets = sheets.filter(enrollment__student__school=request.school)
    sheet = sheets.first()
    if sheet is None:
        return render(request, "results/verify.html", {"missing": True, "code": code})
    return render(
        request, "results/verify.html", {"sheet": sheet, "data": sheet.snapshot, **card_options(sheet.school)}
    )
