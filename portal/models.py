from django.conf import settings
from django.db import models


class ResultPin(models.Model):
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="pins")
    code = models.CharField(max_length=20)
    student = models.ForeignKey("records.Student", null=True, blank=True, on_delete=models.CASCADE, related_name="pins")
    term = models.ForeignKey("schools.Term", null=True, blank=True, on_delete=models.CASCADE, related_name="pins")
    uses_remaining = models.PositiveSmallIntegerField(default=5)
    max_uses = models.PositiveSmallIntegerField(default=5)
    batch_label = models.CharField(max_length=40, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("school", "code")

    def __str__(self):
        return self.code


class PinAttempt(models.Model):
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE)
    admission_number = models.CharField(max_length=40)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class FeeFlag(models.Model):
    class Status(models.TextChoices):
        CLEARED = "cleared", "Cleared"
        PART = "part", "Part payment"
        OWING = "owing", "Owing"

    student = models.ForeignKey("records.Student", on_delete=models.CASCADE, related_name="fee_flags")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="fee_flags")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CLEARED)
    reason = models.CharField(max_length=200, blank=True)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    override_until = models.DateTimeField(null=True, blank=True)
    override_reason = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "term")

    def is_blocked(self):
        if self.status != self.Status.OWING:
            return False
        if not self.student.school.charges_fees:
            return False  # government schools never hold a result for fees
        if self.override_until:
            from django.utils import timezone

            if self.override_until > timezone.now():
                return False
        return True
