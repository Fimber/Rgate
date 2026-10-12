from django.contrib import admin

from ops.models import AuditLog, ImpersonationSession, SmsMessage


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action", "entity", "actor", "school")
    list_filter = ("action",)


admin.site.register(ImpersonationSession)
admin.site.register(SmsMessage)
