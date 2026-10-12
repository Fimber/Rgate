from common.ratelimit import client_ip
from ops.models import AuditLog


def log_action(request, action, entity, instance, before=None, after=None):
    school = getattr(request, "school", None) or getattr(instance, "school", None)
    AuditLog.objects.create(
        school=school if getattr(school, "pk", None) else None,
        actor=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
        action=action,
        entity=entity,
        entity_id=str(getattr(instance, "pk", "") or ""),
        before=before or {},
        after=after or {},
        ip_address=client_ip(request) if request is not None else "",
    )
