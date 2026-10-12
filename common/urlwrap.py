from functools import wraps

from django.urls.resolvers import URLPattern, URLResolver


def drop_school_slug_arg(view):
    if getattr(view, "_drops_school_slug", False):
        return view

    @wraps(view)
    def wrapped(request, *args, school_slug=None, **kwargs):
        return view(request, *args, **kwargs)

    wrapped._drops_school_slug = True
    return wrapped


def absorb_school_slug(patterns):
    """Stop /{slug}/... from being passed into every nested view."""
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            pattern.callback = drop_school_slug_arg(pattern.callback)
        elif isinstance(pattern, URLResolver):
            absorb_school_slug(pattern.url_patterns)
    return patterns
