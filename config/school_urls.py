from django.urls import include, path

from accounts import views as account_views
from common.urlwrap import absorb_school_slug
from results.views import verify_result
from schools import views as school_views

urlpatterns = absorb_school_slug(
    [
        path("", school_views.school_home, name="school_home"),
        path("login/", account_views.login_view, name="school_login"),
        path("forgot-password/", account_views.forgot_password, name="school_forgot"),
        path("logout/", account_views.logout_view, name="school_logout"),
        path("password/", account_views.change_password, name="school_password"),
        path("verify/<str:code>/", verify_result, name="school_verify"),
        path("app/", include("schools.urls")),
        path("app/", include("records.urls")),
        path("app/", include("results.urls")),
        path("portal/", include("portal.urls")),
    ]
)
