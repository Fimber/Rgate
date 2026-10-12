import secrets

from django.db import transaction
from django.utils import timezone

from common.audit import log_action
from results.models import ClassCycle, ResultSheet, SubjectSheet, WorkflowEvent
from results.services.compute import recompute_class, snapshot_sheet
from results.services.notify import notify_result_published
from results.services.pdf import generate_result_pdf


def get_cycle(school_class, term):
    cycle, _ = ClassCycle.objects.get_or_create(school_class=school_class, term=term)
    return cycle


def submit_sheet(request, sheet):
    if sheet.state == SubjectSheet.State.SUBMITTED and not request.user.is_school_admin_like:
        raise PermissionError("This sheet is already submitted.")
    sheet.state = SubjectSheet.State.SUBMITTED
    sheet.submitted_by = request.user
    sheet.submitted_at = timezone.now()
    sheet.save()
    recompute_class(sheet.school_class, sheet.term)
    log_action(request, "submit_sheet", "subject_sheet", sheet, after={"state": sheet.state})
    return sheet


def unlock_sheet(request, sheet):
    if not request.user.is_school_admin_like:
        raise PermissionError("Only an admin can reopen a submitted sheet.")
    sheet.state = SubjectSheet.State.DRAFT
    sheet.save(update_fields=["state"])
    log_action(request, "unlock_sheet", "subject_sheet", sheet)
    return sheet


def review_class(request, school_class, term):
    cycle = get_cycle(school_class, term)
    sheets = SubjectSheet.objects.filter(school_class=school_class, term=term)
    if sheets.exclude(state=SubjectSheet.State.SUBMITTED).exists():
        raise ValueError("Every subject must be submitted before review.")
    recompute_class(school_class, term)
    incompletes = ResultSheet.objects.filter(enrollment__school_class=school_class, term=term, incomplete=True).exclude(
        state__in=[ResultSheet.State.PUBLISHED, ResultSheet.State.ARCHIVED]
    )
    cycle.state = ClassCycle.State.REVIEWED
    cycle.reviewed_by = request.user
    cycle.reviewed_at = timezone.now()
    cycle.save()
    ResultSheet.objects.filter(enrollment__school_class=school_class, term=term).exclude(
        state__in=[ResultSheet.State.PUBLISHED, ResultSheet.State.ARCHIVED]
    ).update(state=ResultSheet.State.REVIEWED)
    WorkflowEvent.objects.create(class_cycle=cycle, from_state="draft", to_state="reviewed", actor=request.user)
    log_action(request, "review_class", "class_cycle", cycle)
    return cycle, incompletes


def approve_class(request, school_class, term):
    cycle = get_cycle(school_class, term)
    if cycle.state not in {ClassCycle.State.REVIEWED, ClassCycle.State.APPROVED}:
        raise ValueError("The class teacher must review this class first.")
    recompute_class(school_class, term)
    cycle.state = ClassCycle.State.APPROVED
    cycle.approved_by = request.user
    cycle.approved_at = timezone.now()
    cycle.save()
    ResultSheet.objects.filter(enrollment__school_class=school_class, term=term).exclude(
        state__in=[ResultSheet.State.PUBLISHED, ResultSheet.State.ARCHIVED]
    ).update(state=ResultSheet.State.APPROVED)
    WorkflowEvent.objects.create(class_cycle=cycle, from_state="reviewed", to_state="approved", actor=request.user)
    log_action(request, "approve_class", "class_cycle", cycle)
    return cycle


@transaction.atomic
def publish_classes(request, term, classes, send_sms=True):
    """Publish every class or none: one failing class rolls the whole batch back."""
    published = []
    for school_class in classes:
        cycle = get_cycle(school_class, term)
        if cycle.state not in {ClassCycle.State.APPROVED, ClassCycle.State.PUBLISHED}:
            raise ValueError(f"{school_class} has not been approved by the head of school.")
        recompute_class(school_class, term)
        sheets = ResultSheet.objects.filter(enrollment__school_class=school_class, term=term).exclude(
            state=ResultSheet.State.ARCHIVED
        )
        loud = [s for s in sheets if s.incomplete]
        if loud:
            names = ", ".join(s.enrollment.student.full_name for s in loud[:8])
            raise ValueError(f"Incomplete results must be resolved before publishing: {names}")
        for sheet in sheets:
            if sheet.state == ResultSheet.State.PUBLISHED:
                continue
            if not sheet.result_code:
                sheet.result_code = secrets.token_hex(6).upper()
            sheet.state = ResultSheet.State.PUBLISHED
            sheet.published_at = timezone.now()
            sheet.published_by = request.user
            sheet.save()
            snapshot_sheet(sheet)
            generate_result_pdf(sheet)
            published.append(sheet)
            if send_sms:
                # Only text parents once the publish has really committed.
                transaction.on_commit(lambda sheet=sheet: notify_result_published(sheet))
        cycle.state = ClassCycle.State.PUBLISHED
        cycle.published_by = request.user
        cycle.published_at = timezone.now()
        cycle.save()
        WorkflowEvent.objects.create(class_cycle=cycle, from_state="approved", to_state="published", actor=request.user)
    log_action(
        request,
        "publish",
        "publication",
        term,
        after={"class_ids": [c.id for c in classes], "count": len(published)},
    )
    return published


def amend_result(request, sheet, reason):
    if sheet.state != ResultSheet.State.PUBLISHED:
        raise ValueError("Only published results are amended.")
    previous = sheet.version
    sheet.state = ResultSheet.State.APPROVED
    sheet.save(update_fields=["state"])
    from results.models import Amendment

    Amendment.objects.create(result_sheet=sheet, previous_version=previous, reason=reason, created_by=request.user)
    log_action(request, "amend_result", "result_sheet", sheet, after={"reason": reason})
    return sheet
