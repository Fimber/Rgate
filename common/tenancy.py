from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


class SchoolScopedQuerySetMixin:
    school_field = "school"

    def get_queryset(self):
        qs = super().get_queryset()
        school = getattr(self.request, "school", None)
        if school is None:
            return qs.none()
        return qs.filter(**{self.school_field: school})


def role_required(*roles):
    def decorator(view):
        @login_required
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            if request.user.is_platform_admin and "platform_admin" in roles:
                return view(request, *args, **kwargs)
            if request.user.role in roles:
                return view(request, *args, **kwargs)
            return HttpResponseForbidden("You do not have access to this page.")

        return _wrapped

    return decorator


def school_staff_required(view):
    @login_required
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_platform_admin:
            return redirect("ops:dashboard")
        if not request.user.is_school_staff:
            return redirect("portal:home")
        if request.school is None:
            return HttpResponseForbidden("No school is selected.")
        if request.user.school_id != request.school.id:
            return HttpResponseForbidden("You do not belong to this school.")
        if not request.school.setup_complete and request.resolver_match.url_name not in {
            "wizard",
            "dashboard",
        }:
            return redirect("schools:wizard")
        return view(request, *args, **kwargs)

    return _wrapped


STAFF_ROLES = (
    "school_admin",
    "head_of_school",
    "class_teacher",
    "subject_teacher",
)
ADMIN_ROLES = ("school_admin", "head_of_school")


def school_admin_required(view):
    """School staff with the admin or head-of-school role."""

    @school_staff_required
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_school_admin_like:
            return HttpResponseForbidden("Only a school admin or head of school can do this.")
        return view(request, *args, **kwargs)

    return _wrapped
