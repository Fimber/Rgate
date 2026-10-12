from common.current import bind_request_school, set_current_school_slug
from schools.models import School
from schools.slugs import RESERVED


class SchoolTenantMiddleware:
    """Resolve the current school from /{slug}/..., subdomain, or session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.school = None
        set_current_school_slug(None)
        school = self._from_path(request) or self._from_host(request)
        if school is None:
            school_id = request.session.get("school_id")
            if school_id:
                school = School.objects.filter(id=school_id).first()

        user = getattr(request, "user", None)
        if user and user.is_authenticated and getattr(user, "school_id", None):
            if school is None or (not user.is_platform_admin and user.school_id != school.id):
                school = user.school

        bind_request_school(request, school)
        canonical = self._canonical_slug_redirect(request, school)
        if canonical:
            return canonical
        response = self.get_response(request)
        return self._keep_login_on_school_path(request, response)

    def _from_path(self, request):
        first = (request.path or "/").strip("/").split("/", 1)[0].lower()
        if not first or first in RESERVED:
            return None
        school = School.objects.filter(slug=first).first()
        if school is None and "-" in first:
            school = School.objects.filter(slug=first.replace("-", "")).first()
        return school

    def _from_host(self, request):
        host = request.get_host().split(":")[0].lower()
        slug = None
        parts = host.split(".")
        if len(parts) >= 3:
            slug = parts[0]
        elif host.endswith(".localhost") and host != "localhost":
            slug = host.split(".")[0]
        if slug and slug not in RESERVED:
            return School.objects.filter(slug=slug, status=School.Status.ACTIVE).first()
        return None

    def _canonical_slug_redirect(self, request, school):
        if not school:
            return None
        first = (request.path or "/").strip("/").split("/", 1)[0].lower()
        if not first or first in RESERVED or first == school.slug.lower():
            return None
        from django.shortcuts import redirect

        suffix = request.get_full_path()[1 + len(first) :]
        return redirect(f"/{school.slug}{suffix}")

    def _keep_login_on_school_path(self, request, response):
        school = getattr(request, "school", None)
        if not school or response.status_code not in (301, 302):
            return response
        location = response.get("Location") or ""
        if location.startswith("/login/"):
            response["Location"] = f"/{school.slug}{location}"
        return response


class PasswordChangeRequiredMiddleware:
    """Send users with a temporary password to the change-password page before anything else."""

    EXEMPT_SUFFIXES = ("/password/", "/logout/", "/impersonate/stop/")
    EXEMPT_PREFIXES = ("/static/", "/media/", "/healthz")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
            and not request.session.get("impersonator_id")
            and not request.path.startswith(self.EXEMPT_PREFIXES)
            and not request.path.endswith(self.EXEMPT_SUFFIXES)
        ):
            from django.contrib import messages
            from django.shortcuts import redirect

            messages.info(request, "Choose a new password to finish signing in.")
            return redirect("accounts:password")
        return self.get_response(request)
