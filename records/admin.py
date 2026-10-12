from django.contrib import admin

from records.models import ClassTeacherAssignment, Enrollment, Student, SubjectAssignment


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("admission_number", "surname", "first_name", "school", "status")
    list_filter = ("school", "status")
    search_fields = ("admission_number", "surname", "first_name")


admin.site.register(Enrollment)
admin.site.register(SubjectAssignment)
admin.site.register(ClassTeacherAssignment)
