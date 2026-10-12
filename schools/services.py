from results.models import CommentBank
from schools.defaults import (
    AFFECTIVE,
    COMMENT_BANK,
    DEFAULT_COMPONENTS,
    DEFAULT_LEVELS,
    NURSERY_SKILLS,
    PRIMARY_GRADES,
    PSYCHOMOTOR,
    SECONDARY_GRADES,
    subjects_for_level,
)
from schools.models import (
    AcademicSession,
    AssessmentComponent,
    BehaviouralTrait,
    GradeBand,
    Level,
    LevelSubject,
    SchoolClass,
    Subject,
    Term,
)


def apply_nigerian_defaults(school, session):
    if not school.levels.exists():
        for index, (name, report_type) in enumerate(DEFAULT_LEVELS):
            Level.objects.create(school=school, name=name, order=index, report_type=report_type)
    for level in school.levels.all():
        if not level.classes.exists():
            for arm in ("A", "B"):
                SchoolClass.objects.create(school=school, level=level, arm=arm, name=f"{level.name} {arm}")
        names = subjects_for_level(level.name)
        for name in names:
            subject, _ = Subject.objects.get_or_create(school=school, name=name)
            LevelSubject.objects.get_or_create(level=level, subject=subject, defaults={"is_core": True})
    if not AssessmentComponent.objects.filter(session=session).exists():
        for name, maximum, order in DEFAULT_COMPONENTS:
            AssessmentComponent.objects.create(
                school=school, session=session, name=name, max_score=maximum, order=order
            )
    if not school.grade_bands.exists():
        for level in school.levels.all():
            bands = SECONDARY_GRADES if level.name.startswith(("JSS", "SSS")) else PRIMARY_GRADES
            if level.report_type == Level.ReportType.SKILLS:
                continue
            for index, (low, high, label, remark) in enumerate(bands):
                GradeBand.objects.create(
                    school=school,
                    level=level,
                    min_score=low,
                    max_score=high,
                    label=label,
                    remark=remark,
                    order=index,
                )
    if not school.traits.exists():
        for index, name in enumerate(AFFECTIVE):
            BehaviouralTrait.objects.create(
                school=school, domain=BehaviouralTrait.Domain.AFFECTIVE, name=name, order=index
            )
        for index, name in enumerate(PSYCHOMOTOR):
            BehaviouralTrait.objects.create(
                school=school, domain=BehaviouralTrait.Domain.PSYCHOMOTOR, name=name, order=index
            )
        for index, name in enumerate(NURSERY_SKILLS):
            BehaviouralTrait.objects.create(school=school, domain=BehaviouralTrait.Domain.SKILL, name=name, order=index)
    if not school.comment_bank.exists():
        for role, low, high, body in COMMENT_BANK:
            CommentBank.objects.create(school=school, role=role, min_average=low, max_average=high, body=body)


def ensure_current_calendar(school, session_name="2025/2026"):
    session, _ = AcademicSession.objects.get_or_create(school=school, name=session_name, defaults={"is_current": True})
    if not school.sessions.filter(is_current=True).exists():
        session.is_current = True
        session.save(update_fields=["is_current"])
    for index, name in enumerate(Term.Name.values):
        term, _ = Term.objects.get_or_create(session=session, name=name)
        if index == 0 and not session.terms.filter(is_current=True).exists():
            term.is_current = True
            term.save(update_fields=["is_current"])
    return session


def clone_session(school, source, new_name):
    target, created = AcademicSession.objects.get_or_create(
        school=school, name=new_name, defaults={"cloned_from": source, "is_current": True}
    )
    school.sessions.exclude(pk=target.pk).update(is_current=False)
    target.is_current = True
    target.cloned_from = source
    target.save()
    for term in source.terms.all():
        Term.objects.get_or_create(session=target, name=term.name)
    for component in source.components.all():
        AssessmentComponent.objects.get_or_create(
            school=school,
            session=target,
            name=component.name,
            defaults={"max_score": component.max_score, "order": component.order},
        )
    return target
