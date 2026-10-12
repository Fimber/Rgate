import secrets
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import User
from common.audit import log_action
from common.current import bind_request_school
from common.parsing import to_int
from common.ratelimit import client_ip, too_many
from common.tenancy import school_admin_required
from portal.models import FeeFlag, PinAttempt, ResultPin
from records.models import Student
from results.models import ResultSheet
from results.services.cards import card_options
from results.services.pdf import generate_result_pdf
from schools.models import School

# No 0/O, 1/I/L: PINs are read off scratch cards and typed on phones.
PIN_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
PIN_LENGTH = 10
MAX_PIN_USES = 20
MAX_OVERRIDE_HOURS = 24 * 14
PIN_SESSION_KEY = "pin_sheet_ids"


def _fee_blocked(student, term):
    flag = FeeFlag.objects.filter(student=student, term=term).first()
    return flag.is_blocked() if flag else False


def _visible_results(student):
    return (
        ResultSheet.objects.filter(
            enrollment__student=student,
            state__in=[ResultSheet.State.PUBLISHED, ResultSheet.State.ARCHIVED],
        )
        .select_related("term", "term__session", "enrollment__school_class")
        .order_by("published_at", "id")
    )


def _flag(student, sheet):
    if not sheet:
        return None
    return FeeFlag.objects.filter(student=student, term=sheet.term).first()


def _can_view(request, sheet):
    """Staff of the same school, the linked parent or student, or a PIN holder for this sheet."""
    student = sheet.enrollment.student
    user = request.user
    if user.is_authenticated:
        if user.is_school_staff and user.school_id == student.school_id:
            return True
        if user.id in {student.parent_user_id, student.student_user_id}:
            return True
    return sheet.id in request.session.get(PIN_SESSION_KEY, [])


def _published_sheet_for_viewer(request, sheet_id):
    sheet = get_object_or_404(
        ResultSheet.objects.select_related("enrollment__student__school", "term__session"),
        pk=sheet_id,
        state__in=[ResultSheet.State.PUBLISHED, ResultSheet.State.ARCHIVED],
    )
    if not _can_view(request, sheet):
        if not request.user.is_authenticated:
            return None
        raise Http404("No result here.")
    return sheet


def _is_staff_of(user, student):
    return user.is_authenticated and user.is_school_staff and user.school_id == student.school_id


@login_required
def home(request):
    if request.user.role != User.Role.PARENT:
        return redirect("accounts:post_login")
    cards = []
    for child in Student.objects.filter(parent_user=request.user).select_related("school"):
        results = list(_visible_results(child))
        latest = results[-1] if results else None
        flag = _flag(child, latest)
        cards.append(
            {"child": child, "results": results, "blocked": flag.is_blocked() if flag else False, "flag": flag}
        )
    return render(request, "portal/home.html", {"cards": cards})


@login_required
def student_home(request):
    if request.user.role != User.Role.STUDENT:
        return redirect("accounts:post_login")
    student = Student.objects.filter(student_user=request.user).first()
    if student is None:
        student = Student.objects.filter(admission_number=request.user.phone, school=request.user.school).first()
    results = list(_visible_results(student)) if student else []
    latest = results[-1] if results else None
    return render(
        request,
        "portal/student.html",
        {
            "student": student,
            "results": results,
            "blocked": _fee_blocked(student, latest.term) if student and latest else False,
        },
    )


def result_view(request, sheet_id):
    sheet = _published_sheet_for_viewer(request, sheet_id)
    if sheet is None:
        return redirect_to_login(request.get_full_path())
    student = sheet.enrollment.student
    if _fee_blocked(student, sheet.term) and not _is_staff_of(request.user, student):
        return render(request, "portal/blocked.html", {"student": student, "school": student.school})
    data = sheet.snapshot
    if not data:
        from results.services.compute import snapshot_sheet

        data = snapshot_sheet(sheet)
    return render(request, "portal/result.html", {"sheet": sheet, "data": data, **card_options(student.school)})


def result_pdf(request, sheet_id):
    sheet = _published_sheet_for_viewer(request, sheet_id)
    if sheet is None:
        return redirect_to_login(request.get_full_path())
    student = sheet.enrollment.student
    if _fee_blocked(student, sheet.term) and not _is_staff_of(request.user, student):
        return render(request, "portal/blocked.html", {"student": student, "school": student.school})
    if not sheet.pdf_file or not sheet.pdf_file.storage.exists(sheet.pdf_file.name):
        generate_result_pdf(sheet)
    return FileResponse(sheet.pdf_file.open("rb"), as_attachment=True, filename=f"{sheet.result_code}.pdf")


def pin_entry(request):
    from accounts.views import _login_context

    school = request.school or School.objects.filter(status=School.Status.ACTIVE).first()
    if request.method != "POST":
        if getattr(request, "school", None):
            return redirect(f"/{request.school.slug}/login/?tab=pin")
        return redirect("/login/?tab=pin")

    admission = (request.POST.get("admission_number") or request.POST.get("admission") or "").strip()
    code = "".join((request.POST.get("pin") or "").split()).upper()
    school_id = to_int(request.POST.get("school")) or (school.id if school else None)
    ip = client_ip(request)
    ctx = _login_context(request, {"tab": "pin", "admission": admission, "selected_school": str(school_id or "")})

    def fail(message):
        ctx["pin_alert"] = message
        return render(request, "accounts/login.html", ctx)

    if too_many(f"pin:{ip}", limit=10, window=300) or too_many(
        f"pin:{school_id}:{admission.upper()}", limit=10, window=3600
    ):
        return fail("Too many PIN attempts. Try again shortly.")
    chosen = School.objects.filter(pk=school_id, status=School.Status.ACTIVE).first()
    if chosen is None:
        return fail("Choose your school and try again.")
    if chosen.portal_mode == School.PortalMode.ACCOUNTS:
        return fail("This school does not use result PINs. Sign in with your parent account.")

    student = Student.objects.filter(school=chosen, admission_number__iexact=admission).first()
    pin = ResultPin.objects.filter(school=chosen, code=code).first()
    ok = bool(student and pin and pin.uses_remaining > 0 and pin.student_id in {None, student.id})
    PinAttempt.objects.create(
        school=chosen, admission_number=admission[:40], ip_address=ip if ip != "unknown" else None, success=ok
    )
    if not ok:
        if pin and student and pin.uses_remaining == 0:
            return fail(
                f"This PIN has been used {pin.max_uses} times. Buy a new one from the bursary to open the result again."
            )
        return fail("Admission number or PIN is not valid.")

    results = _visible_results(student)
    sheet = results.filter(term=pin.term).last() if pin.term_id else results.last()
    if sheet is None:
        # Do not burn a use when there is nothing to show yet.
        return fail("No published result is available for this student yet.")
    if _fee_blocked(student, sheet.term):
        return render(request, "portal/blocked.html", {"student": student, "school": chosen})

    consumed = ResultPin.objects.filter(pk=pin.pk, uses_remaining__gt=0).update(
        uses_remaining=F("uses_remaining") - 1, last_used_at=timezone.now()
    )
    if not consumed:
        return fail("This PIN has no views left. Buy a new one from the bursary.")
    if pin.student_id is None:
        ResultPin.objects.filter(pk=pin.pk, student__isnull=True).update(student=student)

    request.session.cycle_key()
    allowed = set(request.session.get(PIN_SESSION_KEY, []))
    allowed.add(sheet.id)
    request.session[PIN_SESSION_KEY] = sorted(allowed)
    bind_request_school(request, chosen)
    return redirect("portal:result", sheet_id=sheet.id)


@school_admin_required
def fees(request):
    school = request.school
    if not school.charges_fees:
        messages.info(request, "Government schools do not charge fees, so results are never held for owing.")
        return redirect("schools:dashboard")
    term = school.current_term()
    if term is None:
        messages.error(request, "Set the current term before recording fee status.")
        return redirect("schools:dashboard")
    if request.method == "POST":
        action = request.POST.get("action")
        student = get_object_or_404(Student, pk=to_int(request.POST.get("student")), school=school)
        reason = (request.POST.get("reason") or "").strip()[:200]
        if action == "set":
            status = request.POST.get("status")
            if status not in FeeFlag.Status.values:
                messages.error(request, "Choose cleared, part payment or owing.")
                return redirect("portal:fees")
            previous = FeeFlag.objects.filter(student=student, term=term).values_list("status", flat=True).first()
            flag, _ = FeeFlag.objects.update_or_create(
                student=student,
                term=term,
                defaults={
                    "status": status,
                    "reason": reason,
                    "set_by": request.user,
                    "override_until": None,
                    "override_reason": "",
                },
            )
            log_action(request, "fee_status", "fee_flag", flag, before={"status": previous}, after={"status": status})
            messages.success(request, f"Fee status for {student.full_name} updated. Access changes immediately.")
        elif action == "override":
            hours = to_int(request.POST.get("hours"), default=24, minimum=1, maximum=MAX_OVERRIDE_HOURS)
            flag, _ = FeeFlag.objects.get_or_create(
                student=student, term=term, defaults={"status": FeeFlag.Status.OWING, "set_by": request.user}
            )
            flag.override_until = timezone.now() + timedelta(hours=hours)
            flag.override_reason = reason or "Temporary access"
            flag.set_by = request.user
            flag.save()
            log_action(
                request, "fee_override", "fee_flag", flag, after={"hours": hours, "reason": flag.override_reason}
            )
            messages.success(request, f"Temporary access granted for {hours} hours.")
        return redirect("portal:fees")

    flags = {f.student_id: f for f in FeeFlag.objects.filter(student__school=school, term=term)}
    students = list(school.students.filter(status=Student.Status.ACTIVE))
    for student in students:
        student.fee_flag = flags.get(student.id)
    return render(request, "portal/fees.html", {"students": students, "term": term})


def _new_pin_codes(school, count):
    codes = set()
    while len(codes) < count:
        codes.add("".join(secrets.choice(PIN_ALPHABET) for _ in range(PIN_LENGTH)))
    taken = set(ResultPin.objects.filter(school=school, code__in=codes).values_list("code", flat=True))
    return list(codes - taken)


@school_admin_required
def pins(request):
    school = request.school
    term = school.current_term()
    created = []
    if request.method == "POST":
        count = to_int(request.POST.get("count"), default=10, minimum=1, maximum=200)
        uses = to_int(request.POST.get("uses"), default=5, minimum=1, maximum=MAX_PIN_USES)
        batch = (request.POST.get("batch") or timezone.now().strftime("%Y%m%d-%H%M")).strip()[:40]
        student_id = to_int(request.POST.get("student"))
        student = school.students.filter(pk=student_id).first() if student_id else None
        created = ResultPin.objects.bulk_create(
            ResultPin(
                school=school,
                code=code,
                student=student,
                term=term,
                uses_remaining=uses,
                max_uses=uses,
                batch_label=batch,
                created_by=request.user,
            )
            for code in _new_pin_codes(school, count)
        )
        log_action(request, "generate_pins", "result_pin", school, after={"count": len(created), "batch": batch})
        messages.success(request, f"Generated {len(created)} PIN(s). Copy them now; this is the print list.")
    return render(
        request,
        "portal/pins.html",
        {
            "pins": school.pins.select_related("student").order_by("-created_at")[:200],
            "created": created,
            "students": school.students.filter(status=Student.Status.ACTIVE),
            "term": term,
        },
    )
