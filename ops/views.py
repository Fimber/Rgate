from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from common.audit import log_action
from common.parsing import is_hex_colour, to_int
from common.tenancy import role_required
from ops.models import AuditLog, ImpersonationSession, SmsMessage
from records.models import Student
from records.views import PHONE_RE, temporary_password
from results.models import ResultSheet
from schools.models import School
from schools.services import apply_nigerian_defaults, ensure_current_calendar

IMPERSONATOR_KEY = "impersonator_id"
IMPERSONATION_KEY = "impersonation_id"


@role_required("platform_admin")
def dashboard(request):
    schools = School.objects.annotate(student_count=Count("students"))
    return render(
        request,
        "ops/dashboard.html",
        {
            "schools": schools,
            "students": Student.objects.count(),
            "published": ResultSheet.objects.filter(state=ResultSheet.State.PUBLISHED).count(),
            "sms": SmsMessage.objects.filter(status=SmsMessage.Status.SENT).count(),
            "logins": User.objects.filter(last_login__isnull=False).count(),
        },
    )


@role_required("platform_admin")
def school_new(request):
    if request.method == "POST":
        from schools.slugs import unique_school_slug

        name = (request.POST.get("name") or "").strip()
        admin_phone = User.objects.normalize_phone(request.POST.get("admin_phone") or "")
        password = request.POST.get("admin_password") or ""
        colour = request.POST.get("brand_colour") or "#0B3D2E"
        ownership = request.POST.get("ownership") or School.Ownership.PRIVATE
        problem = None
        if ownership not in School.Ownership.values:
            problem = "Choose private or government."
        elif len(name) < 2:
            problem = "Give the school a name."
        elif not PHONE_RE.match(admin_phone):
            problem = "Enter the admin's 11-digit phone number."
        elif User.objects.filter(phone=admin_phone).exists():
            problem = "That admin phone number already has an account."
        elif password and len(password) < 8:
            problem = "The admin password must be at least 8 characters, or leave it blank."
        if problem:
            messages.error(request, problem)
            return render(request, "ops/school_form.html")
        password = password or temporary_password()
        with transaction.atomic():
            school = School.objects.create(
                name=name,
                slug=unique_school_slug((request.POST.get("slug") or "").strip() or name),
                address=(request.POST.get("address") or "").strip(),
                contact_phone=(request.POST.get("contact_phone") or "").strip(),
                brand_colour=colour if is_hex_colour(colour) else "#0B3D2E",
                ownership=ownership,
            )
            session = ensure_current_calendar(school)
            apply_nigerian_defaults(school, session)
            admin = User.objects.create_user(
                phone=admin_phone,
                password=password,
                first_name=(request.POST.get("admin_first") or "School").strip(),
                last_name=(request.POST.get("admin_last") or "Admin").strip(),
                role=User.Role.SCHOOL_ADMIN,
                school=school,
                must_change_password=True,
            )
            log_action(request, "create_school", "school", school, after={"admin": admin.phone})
        messages.success(
            request,
            f"{school.name} created. Admin login is {admin.phone}, temporary password {password}. "
            "Share it privately; it must be changed at first sign-in.",
        )
        return redirect("ops:dashboard")
    return render(request, "ops/school_form.html")


@role_required("platform_admin")
@require_POST
def school_toggle(request, pk):
    school = get_object_or_404(School, pk=pk)
    before = school.status
    school.status = School.Status.SUSPENDED if school.status == School.Status.ACTIVE else School.Status.ACTIVE
    school.save(update_fields=["status"])
    log_action(request, "toggle_school", "school", school, before={"status": before}, after={"status": school.status})
    messages.success(request, f"{school.name} is now {school.get_status_display()}.")
    return redirect("ops:dashboard")


@role_required("platform_admin")
def audit(request):
    return render(request, "ops/audit.html", {"logs": AuditLog.objects.select_related("actor", "school")[:300]})


@role_required("platform_admin")
def impersonate(request):
    if request.method == "POST":
        target = get_object_or_404(
            User.objects.exclude(role=User.Role.PLATFORM_ADMIN).exclude(is_superuser=True),
            pk=to_int(request.POST.get("target")),
            is_active=True,
        )
        if request.POST.get("consent") != "on":
            messages.error(request, "Support impersonation requires recorded consent.")
            return redirect("ops:impersonate")
        staff = request.user
        record = ImpersonationSession.objects.create(
            staff=staff,
            target=target,
            consented=True,
            reason=(request.POST.get("reason") or "Support").strip()[:200],
        )
        log_action(request, "impersonate_start", "user", target, after={"staff": staff.id, "reason": record.reason})
        # login() flushes the session when the user changes, so mark it afterwards.
        login(request, target, backend="accounts.backends.PhoneOrEmailBackend")
        request.session[IMPERSONATOR_KEY] = staff.id
        request.session[IMPERSONATION_KEY] = record.id
        if target.school_id:
            request.session["school_id"] = target.school_id
        messages.warning(request, f"You are impersonating {target.get_full_name()}. This is logged.")
        return redirect("accounts:post_login")
    return render(
        request,
        "ops/impersonate.html",
        {
            "users": User.objects.exclude(role=User.Role.PLATFORM_ADMIN)
            .exclude(is_superuser=True)
            .filter(is_active=True)
            .select_related("school")[:300]
        },
    )


@login_required
@require_POST
def stop_impersonation(request):
    """Reachable by the impersonated session: it is the only way back to HQ."""
    staff_id = request.session.get(IMPERSONATOR_KEY)
    record_id = request.session.get(IMPERSONATION_KEY)
    staff = User.objects.filter(pk=staff_id, is_active=True).first() if staff_id else None
    if staff is None or not staff.is_platform_admin:
        return redirect("accounts:post_login")
    record = ImpersonationSession.objects.filter(pk=record_id, staff=staff).first()
    if record:
        record.ended_at = timezone.now()
        record.save(update_fields=["ended_at"])
    log_action(request, "impersonate_stop", "user", request.user, after={"staff": staff.id})
    login(request, staff, backend="accounts.backends.PhoneOrEmailBackend")
    request.session.pop("school_id", None)
    return redirect("ops:dashboard")
