from django.utils.text import slugify

RESERVED = {
    "django-admin",
    "admin",
    "hq",
    "app",
    "portal",
    "register",
    "login",
    "logout",
    "go",
    "password",
    "forgot-password",
    "terms",
    "privacy",
    "data-processing",
    "verify",
    "static",
    "media",
    "api",
    "accounts",
    "schools",
    "ops",
    "regate",
    "www",
    "healthz",
    "robots.txt",
    "favicon.ico",
}


def make_school_slug(name):
    compact = slugify(name or "").replace("-", "")
    return (compact or "school")[:40]


class SchoolSlugConverter:
    regex = r"[-a-zA-Z0-9_]+"

    def to_python(self, value):
        from schools.models import School

        if value in RESERVED:
            raise ValueError
        if School.objects.filter(slug=value).exists():
            return value
        compact = value.replace("-", "").lower()
        if compact != value.lower() and School.objects.filter(slug=compact).exists():
            return compact
        raise ValueError

    def to_url(self, value):
        return str(value)


def unique_school_slug(name, exclude_id=None):
    from schools.models import School

    base = make_school_slug(name)
    if base in RESERVED:
        base = f"school{base}"[:40]
    slug = base
    n = 2
    qs = School.objects.all()
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    while qs.filter(slug=slug).exists() or slug in RESERVED:
        suffix = str(n)
        slug = f"{base[: 40 - len(suffix)]}{suffix}"
        n += 1
    return slug
