import re

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import User
from common.current import bind_request_school
from common.parsing import to_int
from common.ratelimit import client_ip, too_many
from schools.models import School
from schools.slugs import unique_school_slug

DEMO_ACCOUNTS = [
    {"label": "School admin", "phone": "08011111111", "password": "school1234"},
    {"label": "Head of school", "phone": "08022222222", "password": "head1234"},
    {"label": "Teacher", "phone": "08044444444", "password": "teacher1234"},
    {"label": "Parent", "phone": "08055555501", "password": "parent1234"},
    {"label": "Platform HQ", "phone": "08000000000", "password": "admin1234"},
]


def _demo_accounts_for(school):
    if school is None:
        return DEMO_ACCOUNTS
    phones = set(User.objects.filter(school=school, is_active=True).values_list("phone", flat=True))
    return [account for account in DEMO_ACCOUNTS if account["phone"] in phones]


def _login_context(request, extra=None):
    schools = School.objects.filter(status=School.Status.ACTIVE)
    school = request.school or (schools.first() if schools.count() == 1 else None)
    ctx = {
        "schools": schools,
        "school": school,
        "identifier": "",
        "selected_school": str(school.id) if school else "",
        "admission": "",
        "demo_accounts": _demo_accounts_for(getattr(request, "school", None)),
        "tab": request.GET.get("tab") or "password",
        "next": request.GET.get("next") or "",
        "pw_alert": "",
        "pin_alert": "",
    }
    if extra:
        ctx.update(extra)
    return ctx


STATES = [
    "Abia",
    "Akwa Ibom",
    "Anambra",
    "Bayelsa",
    "Cross River",
    "Delta",
    "Edo",
    "Enugu",
    "FCT",
    "Imo",
    "Kano",
    "Lagos",
    "Ogun",
    "Oyo",
    "Rivers",
]
ROLES = [
    "Proprietor",
    "Principal",
    "Vice principal",
    "Head teacher",
    "Bursar",
    "IT or admin staff",
]


def _register_ctx(**extra):
    ctx = {
        "states": STATES,
        "roles": ROLES,
        "posted": {
            "school": "",
            "state": "",
            "town": "",
            "levels": [],
            "size": "",
            "name": "",
            "role": "",
            "phone": "",
            "email": "",
            "ownership": "private",
        },
        "registered": False,
        "email": "",
        "alert": "",
        "step": 1,
        "school_path": "",
    }
    ctx.update(extra)
    return ctx


def landing(request):
    return render(request, "accounts/landing.html")


PHONE_RE = re.compile(r"^0[7-9][01]\d{8}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
LEVEL_KEYS = {"nursery", "primary", "junior", "senior"}
SIZE_KEYS = {"s", "m", "l", "xl"}


def _keep_level(name, selected):
    if "nursery" in selected and (name.startswith("Nursery") or name == "Creche"):
        return True
    if "primary" in selected and name.startswith("Primary"):
        return True
    if "junior" in selected and name.startswith("JSS"):
        return True
    if "senior" in selected and name.startswith("SSS"):
        return True
    return False


def register_school(request):
    from schools.defaults import DEFAULT_LEVELS
    from schools.models import Level
    from schools.services import apply_nigerian_defaults, ensure_current_calendar

    if request.method != "POST" and request.session.get("just_registered"):
        school = School.objects.filter(id=request.session.get("school_id")).first()
        if school:
            bind_request_school(request, school)
        return render(
            request,
            "accounts/register.html",
            _register_ctx(
                registered=True,
                email=request.session.get("registered_email") or "",
                school_path=f"/{school.slug}/" if school else "",
            ),
        )
    if request.user.is_authenticated and request.user.is_school_staff:
        bind_request_school(request, request.user.school)
        return redirect("schools:dashboard")
    if request.method == "POST":
        if too_many(f"register:{client_ip(request)}", limit=5, window=3600):
            return render(
                request,
                "accounts/register.html",
                _register_ctx(alert="Too many sign-ups from this network. Try again in an hour."),
            )
        posted = {
            "school": (request.POST.get("school") or "").strip(),
            "state": (request.POST.get("state") or "").strip(),
            "town": (request.POST.get("town") or "").strip(),
            "levels": [lv for lv in request.POST.getlist("levels") if lv in LEVEL_KEYS],
            "size": request.POST.get("size") or "",
            "name": (request.POST.get("name") or "").strip(),
            "role": (request.POST.get("role") or "").strip(),
            "phone": (request.POST.get("phone") or "").strip(),
            "email": (request.POST.get("email") or "").strip(),
            "ownership": request.POST.get("ownership") or School.Ownership.PRIVATE,
        }
        password = request.POST.get("password") or ""
        phone = User.objects.normalize_phone(posted["phone"])
        email = posted["email"]
        step1_ok = (
            len(posted["school"]) >= 2
            and posted["state"] in STATES
            and len(posted["town"]) >= 2
            and posted["levels"]
            and posted["size"] in SIZE_KEYS
            and posted["ownership"] in School.Ownership.values
        )
        step2_ok = (
            len(posted["name"]) >= 2
            and posted["role"] in ROLES
            and bool(PHONE_RE.match(phone))
            and bool(EMAIL_RE.match(email))
            and len(password) >= 8
        )
        if not step1_ok:
            return render(
                request,
                "accounts/register.html",
                _register_ctx(posted=posted, step=1, alert="Please finish telling us about your school."),
            )
        if not step2_ok:
            return render(
                request,
                "accounts/register.html",
                _register_ctx(posted=posted, step=2, alert="Check the account details and try again."),
            )
        if User.objects.filter(phone=phone).exists() or User.objects.filter(email__iexact=email).exists():
            return render(
                request,
                "accounts/register.html",
                _register_ctx(
                    posted=posted,
                    step=2,
                    alert="An account already uses that phone or email. Sign in instead, or use another address.",
                ),
            )
        parts = posted["name"].split()
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else "Admin"
        address = ", ".join(p for p in (posted["town"], posted["state"]) if p)
        slug = unique_school_slug(posted["school"])
        with transaction.atomic():
            school = School.objects.create(
                name=posted["school"],
                slug=slug,
                address=address,
                contact_phone=phone,
                contact_email=email,
                ownership=posted["ownership"],
            )
            for index, (level_name, report_type) in enumerate(DEFAULT_LEVELS):
                if _keep_level(level_name, posted["levels"]):
                    Level.objects.create(school=school, name=level_name, order=index, report_type=report_type)
            session = ensure_current_calendar(school)
            apply_nigerian_defaults(school, session)
            admin = User.objects.create_user(
                phone=phone,
                password=password,
                first_name=first,
                last_name=last,
                email=email,
                role=User.Role.SCHOOL_ADMIN,
                school=school,
            )
        request.session["just_registered"] = True
        request.session["registered_email"] = email
        login(request, admin, backend="accounts.backends.PhoneOrEmailBackend")
        bind_request_school(request, school)
        return redirect("accounts:register")
    return render(request, "accounts/register.html", _register_ctx())


def terms(request):
    return render(request, "accounts/legal.html", {"title": "Terms of use", "kind": "terms"})


def dpa(request):
    return render(request, "accounts/legal.html", {"title": "Data processing agreement", "kind": "dpa"})


def login_view(request):
    if request.user.is_authenticated:
        if request.user.school:
            bind_request_school(request, request.user.school)
        return redirect("accounts:post_login")
    if request.method == "POST":
        identifier = (request.POST.get("identifier") or "").strip()
        password = request.POST.get("password") or ""
        school_id = request.POST.get("school") or ""
        ctx = _login_context(request, {"identifier": identifier, "selected_school": school_id, "tab": "password"})
        ip = client_ip(request)
        account_key = User.objects.normalize_phone(identifier) or identifier.lower()
        # Per IP+account stops a single guesser; per account alone stops a botnet on one victim.
        if too_many(f"login:{ip}:{account_key}", limit=8, window=300) or too_many(
            f"login-account:{account_key}", limit=20, window=900
        ):
            ctx["pw_alert"] = "Too many login attempts. Wait a few minutes and try again."
            return render(request, "accounts/login.html", ctx)
        user = authenticate(request, username=identifier, password=password)
        if user is not None:
            path_school = getattr(request, "school", None)
            login(request, user)
            if user.school:
                bind_request_school(request, user.school)
            elif to_int(school_id):
                bind_request_school(request, School.objects.filter(pk=to_int(school_id)).first())
            if request.POST.get("remember"):
                request.session.set_expiry(60 * 60 * 24 * 30)
            else:
                request.session.set_expiry(60 * 60 * 8)
            next_url = request.POST.get("next") or request.GET.get("next") or ""
            if not url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                next_url = ""
            if path_school and user.school_id and user.school_id != path_school.id:
                return redirect("accounts:post_login")
            return redirect(next_url or "accounts:post_login")
        ctx["pw_alert"] = "That email and password do not match. Check for a space at the end, or reset your password."
        return render(request, "accounts/login.html", ctx)
    ctx = _login_context(request)
    for message in messages.get_messages(request):
        text = str(message)
        if "PIN" in text or "pin" in text.lower() or "admission" in text.lower():
            ctx["tab"] = "pin"
            ctx["pin_alert"] = text
        else:
            ctx["pw_alert"] = text
    return render(request, "accounts/login.html", ctx)


def forgot_password(request):
    return render(request, "accounts/forgot.html")


@require_POST
def logout_view(request):
    slug = request.school.slug if getattr(request, "school", None) else None
    logout(request)
    if slug:
        return redirect("school_login", school_slug=slug)
    return redirect("accounts:login")


@login_required
def post_login(request):
    user = request.user
    if user.school:
        bind_request_school(request, user.school)
    if user.is_platform_admin:
        return redirect("ops:dashboard")
    if user.role == User.Role.PARENT:
        return redirect("portal:home")
    if user.role == User.Role.STUDENT:
        return redirect("portal:student")
    if user.school and not user.school.setup_complete:
        return redirect("schools:wizard")
    return redirect("schools:dashboard")


def legacy_tenant_redirect(request, rest=""):
    school = getattr(request, "school", None)
    if school:
        return redirect(f"/{school.slug}{request.get_full_path()}")
    return redirect("accounts:login")


def verify_legacy(request, code):
    from results.models import ResultSheet

    sheet = ResultSheet.objects.filter(result_code__iexact=code).select_related("enrollment__student__school").first()
    school = getattr(sheet.enrollment.student, "school", None) if sheet else None
    if school:
        bind_request_school(request, school)
        return redirect("school_verify", school_slug=school.slug, code=code)
    return redirect("accounts:login")


def privacy(request):
    return render(request, "accounts/privacy.html")


@login_required
def change_password(request):
    if request.method == "POST":
        current = request.POST.get("current") or ""
        new = request.POST.get("new") or ""
        confirm = request.POST.get("confirm") or ""
        problems = []
        if not request.user.check_password(current):
            problems = ["Current password is wrong."]
        elif new != confirm:
            problems = ["The new passwords do not match."]
        elif new == current:
            problems = ["Choose a password you have not used here before."]
        else:
            try:
                validate_password(new, request.user)
            except ValidationError as exc:
                problems = exc.messages
        if problems:
            for problem in problems:
                messages.error(request, problem)
        else:
            request.user.set_password(new)
            request.user.must_change_password = False
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, "Password updated.")
            return redirect("accounts:post_login")
    return render(request, "accounts/password.html")
