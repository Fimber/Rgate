from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from common.current import bind_request_school
from common.parsing import is_hex_colour, to_decimal, to_int
from common.tenancy import school_staff_required
from common.uploads import clean_image
from records.models import Student
from results.models import ClassCycle, ResultSheet, SubjectSheet
from results.services.cards import TEMPLATES as CARD_TEMPLATES
from schools.models import (
    AcademicSession,
    AssessmentComponent,
    Level,
    LevelSubject,
    School,
    SchoolClass,
    Subject,
    Term,
)
from schools.services import apply_nigerian_defaults, clone_session, ensure_current_calendar

TEXT_FIELDS = {
    "name": 200,
    "address": 300,
    "motto": 200,
    "contact_phone": 20,
    "bursary_contact": 200,
    "owing_message": 1000,
}
CHOICE_FIELDS = {
    "ownership": School.Ownership,
    "portal_mode": School.PortalMode,
    "result_template": School.ResultTemplate,
    "tie_display": School.TieDisplay,
    "incomplete_rule": School.IncompleteRule,
    "average_formula": School.AverageFormula,
}


def apply_school_settings(school, data, files):
    """Copy posted settings onto ``school``, validating each one. Returns a list of problems.

    Only fields present in the POST are touched, so partial forms (wizard steps) work.
    """
    errors = []
    for field, limit in TEXT_FIELDS.items():
        if field in data:
            value = (data.get(field) or "").strip()
            if field == "name" and not value:
                errors.append("The school needs a name.")
                continue
            if field == "owing_message" and not value:
                continue  # keep the default wording rather than show parents a blank page
            setattr(school, field, value[:limit])
    if "contact_email" in data:
        email = (data.get("contact_email") or "").strip()
        try:
            if email:
                validate_email(email)
            school.contact_email = email
        except ValidationError:
            errors.append("Contact email does not look right.")
    if data.get("brand_colour"):
        if is_hex_colour(data["brand_colour"]):
            school.brand_colour = data["brand_colour"].upper()
        else:
            errors.append("Brand colour must be a hex colour like #0B3D2E.")
    for field, choices in CHOICE_FIELDS.items():
        if data.get(field):
            if data[field] in choices.values:
                setattr(school, field, data[field])
            else:
                errors.append(f"Unknown option for {field.replace('_', ' ')}.")
    if data.get("pass_threshold"):
        threshold = to_decimal(data["pass_threshold"])
        if threshold is None or not 0 <= threshold <= 100:
            errors.append("Pass mark must be a number from 0 to 100.")
        else:
            school.pass_threshold = threshold
    if "teachers_self_assign" in data:
        school.teachers_self_assign = data.getlist("teachers_self_assign")[-1] == "1"
    if "show_positions" in data:
        # The form posts a hidden "0" then the checkbox "1", so the last value wins.
        school.show_positions = data.getlist("show_positions")[-1] == "1"
    for field in ("logo", "stamp"):
        if files.get(field):
            try:
                setattr(school, field, clean_image(files[field]))
            except ValidationError as exc:
                errors.extend(f"{field.title()}: {m}" for m in exc.messages)
    return errors


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


MAX_COMPONENT_SCORE = 1000


def save_assessment_components(school, session, names, maxima):
    """Replace this session's components with the posted list. Returns (total, count).

    Any total is allowed: schools mark out of whatever they like, and grading uses the
    percentage of that total. Components are matched by name, so changing a maximum keeps
    the scores already entered. Nothing is touched when the list has no valid component.
    """
    wanted = []
    seen = set()
    for name, maximum in zip(names, maxima):
        name = (name or "").strip()[:60]
        maximum = to_int(maximum)
        if not name or name.lower() in seen or maximum is None or not 1 <= maximum <= MAX_COMPONENT_SCORE:
            continue
        seen.add(name.lower())
        wanted.append((name, maximum))
    if not wanted:
        return 0, 0
    existing = {c.name.lower(): c for c in AssessmentComponent.objects.filter(session=session)}
    with transaction.atomic():
        for order, (name, maximum) in enumerate(wanted):
            component = existing.pop(name.lower(), None)
            if component is None:
                AssessmentComponent.objects.create(
                    school=school, session=session, name=name, max_score=maximum, order=order
                )
            else:
                component.name, component.max_score, component.order = name, maximum, order
                component.save(update_fields=["name", "max_score", "order"])
        # Only components taken off the list lose their scores.
        AssessmentComponent.objects.filter(pk__in=[c.pk for c in existing.values()]).delete()
    return sum(m for _, m in wanted), len(wanted)


def school_home(request, school_slug=None):
    school = request.school
    if school is None:
        school = get_object_or_404(School, slug=school_slug)
        bind_request_school(request, school)
    if request.user.is_authenticated:
        return redirect("accounts:post_login")
    return redirect("school_login", school_slug=school.slug)


@school_staff_required
def dashboard(request):
    school = request.school
    term = school.current_term()
    session = school.current_session()
    stats = {
        "students": school.students.filter(status=Student.Status.ACTIVE).count(),
        "staff": school.users.filter(is_active=True).exclude(role__in=["parent", "student"]).count(),
        "classes": school.classes.count(),
        "published": ResultSheet.objects.filter(
            enrollment__student__school=school, state=ResultSheet.State.PUBLISHED
        ).count()
        if term
        else 0,
    }
    progress = []
    if term:
        for school_class in school.classes.select_related("level")[:24]:
            subjects = LevelSubject.objects.filter(level=school_class.level).count()
            sheets = SubjectSheet.objects.filter(school_class=school_class, term=term)
            submitted = sheets.filter(state=SubjectSheet.State.SUBMITTED).count()
            started = sheets.count()
            cycle = ClassCycle.objects.filter(school_class=school_class, term=term).first()
            progress.append(
                {
                    "class": school_class,
                    "subjects": subjects,
                    "submitted": submitted,
                    "started": started,
                    "state": cycle.state if cycle else "draft",
                }
            )
    return render(
        request,
        "schools/dashboard.html",
        {"stats": stats, "term": term, "session": session, "progress": progress},
    )


@school_staff_required
def wizard(request):
    school = request.school
    if not request.user.is_school_admin_like:
        messages.error(request, "Only a school admin can run setup.")
        return redirect("schools:dashboard")
    session = school.current_session() or ensure_current_calendar(school)
    term = school.current_term()
    step = to_int(request.GET.get("step"), default=school.setup_step or 1, minimum=1, maximum=5)
    if request.method == "POST":
        step = to_int(request.POST.get("step"), default=step, minimum=1, maximum=5)
        if step == 1:
            errors = apply_school_settings(school, request.POST, request.FILES)
            if errors:
                for error in errors:
                    messages.error(request, error)
                return redirect(f"{request.path}?step=1")
            school.setup_step = 2
            school.save()
            return redirect(f"{request.path}?step=2")
        if step == 2:
            if request.POST.get("clone_from"):
                source = get_object_or_404(AcademicSession, pk=request.POST["clone_from"], school=school)
                clone_session(school, source, request.POST.get("session_name") or "2025/2026")
            else:
                name = request.POST.get("session_name") or "2025/2026"
                school.sessions.update(is_current=False)
                session, _ = AcademicSession.objects.update_or_create(
                    school=school, name=name, defaults={"is_current": True}
                )
                for term_name in Term.Name.values:
                    Term.objects.get_or_create(session=session, name=term_name)
                current_name = request.POST.get("current_term") or Term.Name.FIRST
                session.terms.update(is_current=False)
                session.terms.filter(name=current_name).update(is_current=True)
                for t in session.terms.all():
                    prefix = t.name.lower()
                    start = _parse_date(request.POST.get(f"{prefix}_start"))
                    end = _parse_date(request.POST.get(f"{prefix}_end"))
                    resume = _parse_date(request.POST.get(f"{prefix}_resume"))
                    days = to_int(request.POST.get(f"{prefix}_days"), minimum=0, maximum=200)
                    if start:
                        t.start_date = start
                    if end:
                        t.end_date = end
                    if resume:
                        t.resumption_date = resume
                    if days is not None:
                        t.days_opened = days
                    t.save()
            school.setup_step = 3
            school.save(update_fields=["setup_step"])
            return redirect(f"{request.path}?step=3")
        if step == 3:
            if request.POST.get("use_defaults"):
                apply_nigerian_defaults(school, school.current_session())
            school.setup_step = 4
            school.save(update_fields=["setup_step"])
            return redirect(f"{request.path}?step=4")
        if step == 4:
            session = school.current_session()
            total, created = save_assessment_components(
                school, session, request.POST.getlist("component_name"), request.POST.getlist("component_max")
            )
            if created < 1:
                messages.error(request, "Add at least one assessment component with a maximum score.")
                return redirect(f"{request.path}?step=4")
            messages.success(request, f"Saved {created} component(s). Scores are out of {total}.")
            school.setup_step = 5
            school.save(update_fields=["setup_step"])
            return redirect(f"{request.path}?step=5")
        if step == 5:
            errors = apply_school_settings(school, request.POST, {})
            if errors:
                for error in errors:
                    messages.error(request, error)
                return redirect(f"{request.path}?step=5")
            school.setup_complete = True
            school.setup_step = 6
            school.save()
            messages.success(request, "School setup is complete. You can import students next.")
            return redirect("records:students")
    components = AssessmentComponent.objects.filter(session=session)
    return render(
        request,
        "schools/wizard.html",
        {
            "step": step,
            "session": session,
            "term": term,
            "sessions": school.sessions.all(),
            "levels": school.levels.prefetch_related("classes", "level_subjects__subject"),
            "components": components,
            "component_total": sum(c.max_score for c in components),
            "card_templates": CARD_TEMPLATES,
        },
    )


def _forget_cached_pdfs(school):
    """Published PDFs are regenerated on next download after the card layout changes."""
    from results.models import ResultSheet

    ResultSheet.objects.filter(enrollment__student__school=school).exclude(pdf_file="").update(pdf_file="")


@school_staff_required
def settings_view(request):
    school = request.school
    if request.method == "POST" and request.user.is_school_admin_like:
        layout_before = (school.result_template, school.show_positions, school.brand_colour)
        errors = apply_school_settings(school, request.POST, request.FILES)
        if errors:
            school.refresh_from_db()
            for error in errors:
                messages.error(request, error)
        else:
            school.save()
            if (school.result_template, school.show_positions, school.brand_colour) != layout_before:
                _forget_cached_pdfs(school)
            messages.success(request, "School settings saved.")
        return redirect("schools:settings")
    return render(request, "schools/settings.html", {"card_templates": CARD_TEMPLATES})


@school_staff_required
def structure(request):
    school = request.school
    session = school.current_session()
    if request.method == "POST" and request.user.is_school_admin_like:
        action = request.POST.get("action")
        if action == "add_class":
            level = get_object_or_404(Level, pk=request.POST.get("level"), school=school)
            arm = (request.POST.get("arm") or "A").strip()
            SchoolClass.objects.get_or_create(
                school=school, level=level, arm=arm, defaults={"name": f"{level.name} {arm}"}
            )
        elif action == "add_subject":
            name = (request.POST.get("subject_name") or "").strip()
            level = get_object_or_404(Level, pk=request.POST.get("level"), school=school)
            if name:
                subject, _ = Subject.objects.get_or_create(school=school, name=name)
                LevelSubject.objects.get_or_create(
                    level=level, subject=subject, defaults={"is_core": request.POST.get("is_core") == "on"}
                )
        elif action == "save_components":
            if not session:
                messages.error(request, "Create a session first.")
            else:
                total, created = save_assessment_components(
                    school,
                    session,
                    request.POST.getlist("component_name"),
                    request.POST.getlist("component_max"),
                )
                if created < 1:
                    messages.error(request, "Add at least one assessment component with a maximum score.")
                else:
                    messages.success(request, f"Assessment components saved. Scores are out of {total}.")
            return redirect("schools:structure")
        elif action == "defaults":
            apply_nigerian_defaults(school, session)
        messages.success(request, "Structure updated.")
        return redirect("schools:structure")
    components = list(AssessmentComponent.objects.filter(session=session)) if session else []
    return render(
        request,
        "schools/structure.html",
        {
            "levels": school.levels.prefetch_related("classes", "level_subjects__subject"),
            "components": components,
            "component_total": sum(c.max_score for c in components),
            "bands": school.grade_bands.select_related("level"),
            "traits": school.traits.all(),
        },
    )
