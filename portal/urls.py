from django.urls import path

from portal import views

app_name = "portal"

urlpatterns = [
    path("", views.home, name="home"),
    path("student/", views.student_home, name="student"),
    path("result/<int:sheet_id>/", views.result_view, name="result"),
    path("result/<int:sheet_id>/pdf/", views.result_pdf, name="result_pdf"),
    path("pin/", views.pin_entry, name="pin"),
    path("fees/", views.fees, name="fees"),
    path("pins/", views.pins, name="pins"),
]
