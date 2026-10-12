from contextvars import ContextVar

_school_slug = ContextVar("school_slug", default=None)


def set_current_school_slug(slug):
    _school_slug.set(slug or None)


def get_current_school_slug():
    return _school_slug.get()


def bind_request_school(request, school):
    request.school = school
    if school:
        request.session["school_id"] = school.id
        set_current_school_slug(school.slug)
    else:
        set_current_school_slug(None)
