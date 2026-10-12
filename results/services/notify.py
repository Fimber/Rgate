import logging

from django.conf import settings
from django.utils import timezone

from ops.models import SmsMessage

logger = logging.getLogger(__name__)


class SmsProvider:
    def send(self, phone, body):
        raise NotImplementedError


class ConsoleSmsProvider(SmsProvider):
    def send(self, phone, body):
        logger.info("[SMS %s] to %s: %s", settings.SMS_SENDER_ID, phone, body)
        return f"console-{timezone.now().timestamp()}"


def get_provider():
    return ConsoleSmsProvider()


def notify_result_published(sheet):
    student = sheet.enrollment.student
    phone = student.parent_phone
    if not phone:
        return None
    term = sheet.term
    body = (
        f"{student.first_name}'s {term.name} Term {term.session.name} result is ready. "
        f"Open {settings.PLATFORM_DOMAIN}/{student.school.slug}/login/?tab=pin"
    )[:320]
    return _send(sheet.school, student, phone, body)


def send_parent_invite(school, parent, password):
    """Text a new parent their sign-in details. They must change the password at first sign-in."""
    body = (
        f"{school.name} opened a ReGate results account for you. "
        f"Sign in at {settings.PLATFORM_DOMAIN}/{school.slug}/login/ with {parent.phone} "
        f"and temporary password {password}"
    )[:320]
    return _send(school, None, parent.phone, body, stored_body=body.replace(password, "********"))


def _send(school, student, phone, body, stored_body=None):
    """Send through the provider and keep a record. ``stored_body`` keeps secrets out of the table."""
    message = SmsMessage.objects.create(
        school=school,
        student=student,
        phone=phone,
        body=stored_body or body,
        status=SmsMessage.Status.QUEUED,
    )
    try:
        ref = get_provider().send(phone, body)
        message.status = SmsMessage.Status.SENT
        message.provider_ref = ref or ""
        message.sent_at = timezone.now()
        message.save()
    except Exception as exc:  # provider swap should not block publish
        logger.exception("SMS to %s failed", phone)
        message.status = SmsMessage.Status.FAILED
        message.provider_ref = str(exc)[:80]
        message.save()
    return message
