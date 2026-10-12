from django.urls import path

from ops import views

app_name = "ops"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("schools/new/", views.school_new, name="school_new"),
    path("schools/<int:pk>/toggle/", views.school_toggle, name="school_toggle"),
    path("audit/", views.audit, name="audit"),
    path("impersonate/", views.impersonate, name="impersonate"),
    path("impersonate/stop/", views.stop_impersonation, name="stop_impersonation"),
]
