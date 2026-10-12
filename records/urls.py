from django.urls import path

from records import views

app_name = "records"

urlpatterns = [
    path("students/", views.students, name="students"),
    path("students/new/", views.student_edit, name="student_new"),
    path("students/<int:pk>/", views.student_edit, name="student_edit"),
    path("students/import/", views.student_import, name="student_import"),
    path("students/template.xlsx", views.student_template_download, name="student_template"),
    path("students/enroll/", views.carry_enrollments, name="carry_enrollments"),
    path("staff/", views.staff_list, name="staff"),
    path("assignments/", views.assignments, name="assignments"),
    path("my-classes/", views.my_classes, name="my_classes"),
    path("export.xlsx", views.school_export, name="export"),
]
