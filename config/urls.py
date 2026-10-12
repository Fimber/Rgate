from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path, re_path, register_converter
from django.views.decorators.cache import never_cache

from accounts.views import legacy_tenant_redirect
from portal.views import pin_entry
from schools.slugs import SchoolSlugConverter

admin.site.site_header = "ReGate"
admin.site.site_title = "ReGate"
admin.site.index_title = "Platform control"

register_converter(SchoolSlugConverter, "school")


@never_cache
def healthz(request):
    """Load balancer probe: the process is up and the database answers."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # pragma: no cover - exercised only when the DB is down
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("django-admin/", admin.site.urls),
    path("hq/", include("ops.urls")),
    path("", include("accounts.urls")),
    path("portal/pin/", pin_entry, name="hub_pin"),
    re_path(r"^app/", legacy_tenant_redirect),
    re_path(r"^portal/", legacy_tenant_redirect),
    path("<school:school_slug>/", include("config.school_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
