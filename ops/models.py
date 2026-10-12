from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    school = models.ForeignKey("schools.School", null=True, blank=True, on_delete=models.SET_NULL)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    entity = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=40, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    ip_address = models.CharField(max_length=45, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.action} {self.entity} {self.timestamp}"


class ImpersonationSession(models.Model):
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="impersonations")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="impersonated_by")
    consented = models.BooleanField(default=False)
    reason = models.CharField(max_length=200)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]


class SmsMessage(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="sms_messages")
    student = models.ForeignKey("records.Student", null=True, blank=True, on_delete=models.SET_NULL)
    phone = models.CharField(max_length=20)
    body = models.CharField(max_length=320)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    provider_ref = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
