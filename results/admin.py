from django.contrib import admin

from results.models import (
    Amendment,
    ClassCycle,
    Comment,
    CommentBank,
    Publication,
    ResultSheet,
    Score,
    SubjectSheet,
)

admin.site.register(SubjectSheet)
admin.site.register(Score)
admin.site.register(ResultSheet)
admin.site.register(ClassCycle)
admin.site.register(Comment)
admin.site.register(CommentBank)
admin.site.register(Publication)
admin.site.register(Amendment)
