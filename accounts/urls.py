from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("register/", views.register_school, name="register"),
    path("terms/", views.terms, name="terms"),
    path("data-processing/", views.dpa, name="dpa"),
    path("login/", views.login_view, name="login"),
    path("forgot-password/", views.forgot_password, name="forgot"),
    path("logout/", views.logout_view, name="logout"),
    path("go/", views.post_login, name="post_login"),
    path("password/", views.change_password, name="password"),
    path("verify/<str:code>/", views.verify_legacy, name="verify"),
    path("privacy/", views.privacy, name="privacy"),
]
