from django.urls import NoReverseMatch
from django.urls import reverse as django_reverse

from common.current import get_current_school_slug

_installed = False


def reverse(viewname, urlconf=None, args=None, kwargs=None, current_app=None):
    kwargs = dict(kwargs or {})
    args = list(args or [])
    try:
        return django_reverse(viewname, urlconf=urlconf, args=args, kwargs=kwargs, current_app=current_app)
    except NoReverseMatch:
        slug = get_current_school_slug()
        if not slug:
            raise
        if args:
            return django_reverse(
                viewname,
                urlconf=urlconf,
                args=[slug, *args],
                kwargs=kwargs,
                current_app=current_app,
            )
        if "school_slug" not in kwargs:
            kwargs["school_slug"] = slug
            return django_reverse(viewname, urlconf=urlconf, args=args, kwargs=kwargs, current_app=current_app)
        raise


def install():
    global _installed
    if _installed:
        return
    import django.shortcuts
    import django.urls
    import django.urls.base

    django.urls.reverse = reverse
    django.urls.base.reverse = reverse
    django.shortcuts.reverse = reverse
    _installed = True
