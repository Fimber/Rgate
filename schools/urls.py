from django.urls import path

from schools import views

app_name = "schools"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("setup/", views.wizard, name="wizard"),
    path("settings/", views.settings_view, name="settings"),
    path("structure/", views.structure, name="structure"),
]
