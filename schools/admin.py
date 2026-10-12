from django.contrib import admin

from schools.models import (
    AcademicSession,
    AssessmentComponent,
    BehaviouralTrait,
    GradeBand,
    Level,
    LevelSubject,
    School,
    SchoolClass,
    Subject,
    Term,
)


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "setup_complete")
    prepopulated_fields = {"slug": ("name",)}


admin.site.register(AcademicSession)
admin.site.register(Term)
admin.site.register(Level)
admin.site.register(SchoolClass)
admin.site.register(Subject)
admin.site.register(LevelSubject)
admin.site.register(AssessmentComponent)
admin.site.register(GradeBand)
admin.site.register(BehaviouralTrait)
