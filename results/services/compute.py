from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from records.models import Enrollment
from results.models import BehaviouralRating, ResultSheet, Score, SubjectResult
from schools.models import AssessmentComponent, GradeBand, LevelSubject

TWO = Decimal("0.01")


def money(value):
    if value is None:
        return None
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def ordinal(n):
    if n is None:
        return "—"
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def format_position(n, tied, school):
    if n is None:
        return "—"
    label = ordinal(n)
    if tied and school.tie_display == school.TieDisplay.POSITION_TIE:
        return f"{label} (tie)"
    return label


def percent_of(total, out_of):
    """A subject total as a percentage of the session's maximum (unchanged when it is out of 100)."""
    if total is None:
        return None
    if out_of == 100:
        return total
    return money(Decimal(total) * 100 / out_of)


def grade_bands(school, level):
    """Bands for this level (falling back to school-wide), highest first."""
    bands = list(GradeBand.objects.filter(school=school, level=level))
    if not bands:
        bands = list(GradeBand.objects.filter(school=school, level__isnull=True))
    return sorted(bands, key=lambda band: band.min_score, reverse=True)


def grade_for(school, level, total, bands=None):
    """The band whose floor the total reaches. Gaps such as 69.99 -> 70 cannot drop a grade."""
    if total is None:
        return "", ""
    for band in bands if bands is not None else grade_bands(school, level):
        if band.min_score <= total:
            return band.label, band.remark
    return "", ""


def _components(session):
    return list(AssessmentComponent.objects.filter(session=session))


def _subjects_for_level(level):
    return list(LevelSubject.objects.filter(level=level).select_related("subject"))


def subject_total(enrollment, subject, components, school, scores=None):
    """Total one subject. ``scores`` ({component_id: Score}) skips the query when prefetched."""
    if scores is None:
        scores = {
            s.component_id: s
            for s in Score.objects.filter(enrollment=enrollment, subject=subject, component__in=components)
        }
    total = Decimal("0")
    present = 0
    missing = False
    values = {}
    joined_skip = set(enrollment.joined_after_components or [])
    for component in components:
        score = scores.get(component.id)
        key = component.name
        if component.id in joined_skip or (score and score.marker == Score.Marker.EXEMPT):
            values[key] = "EX"
            continue
        if score is None:
            missing = True
            values[key] = ""
            continue
        if score.marker == Score.Marker.ABSENT:
            values[key] = "AB"
            if not school.exclude_absent_from_average:
                missing = True
            continue
        if score.value is None:
            missing = True
            values[key] = ""
            continue
        total += Decimal(score.value)
        present += 1
        values[key] = str(money(score.value))
    if present == 0:
        return None, True, values
    return money(total), missing, values


@transaction.atomic
def recompute_class(school_class, term):
    school = school_class.school
    session = term.session
    components = _components(session)
    # Schools mark out of any total; grades, averages and the pass mark work on percentages.
    out_of = Decimal(sum(c.max_score for c in components)) or Decimal(100)
    level_subjects = _subjects_for_level(school_class.level)
    enrollments = list(
        Enrollment.objects.filter(school_class=school_class, term=term, status=Enrollment.Status.ACTIVE)
        .select_related("student")
        .order_by("student__surname", "student__first_name")
    )
    if not enrollments:
        return []

    # Read everything once; the loops below must not query per student or per subject.
    score_map = defaultdict(dict)
    for score in Score.objects.filter(enrollment__in=enrollments, component__in=components):
        score_map[(score.enrollment_id, score.subject_id)][score.component_id] = score
    bands = grade_bands(school, school_class.level)
    session_terms = list(session.terms.all())
    other_averages = _other_term_averages([e.student_id for e in enrollments], session_terms, term)
    latest_sheets = {}
    for existing in ResultSheet.objects.filter(enrollment__in=enrollments, term=term).order_by("-version"):
        latest_sheets.setdefault(existing.enrollment_id, existing)

    per_student = []
    subject_totals = defaultdict(list)

    for enrollment in enrollments:
        subjects = []
        running = Decimal("0")
        running_percent = Decimal("0")
        offered = 0
        incomplete = False
        for ls in level_subjects:
            total, missing, values = subject_total(
                enrollment, ls.subject, components, school, scores=score_map[(enrollment.id, ls.subject_id)]
            )
            if total is None and missing:
                if ls.is_core:
                    incomplete = True
                subjects.append(
                    {
                        "subject": ls.subject,
                        "total": None,
                        "incomplete": True,
                        "values": values,
                        "is_core": ls.is_core,
                    }
                )
                continue
            if total is None:
                continue
            offered += 1
            running += total
            running_percent += percent_of(total, out_of)
            if missing and school.incomplete_rule == school.IncompleteRule.BLOCK:
                incomplete = True
            subjects.append(
                {
                    "subject": ls.subject,
                    "total": total,
                    "incomplete": missing,
                    "values": values,
                    "is_core": ls.is_core,
                }
            )
            if not missing:
                subject_totals[ls.subject.id].append(total)
        average = money(running_percent / offered) if offered else None
        if incomplete and school.incomplete_rule == school.IncompleteRule.BLOCK:
            positionable = False
        else:
            positionable = average is not None
        per_student.append(
            {
                "enrollment": enrollment,
                "subjects": subjects,
                "total": money(running) if offered else None,
                "average": average,
                "offered": offered,
                "incomplete": incomplete,
                "positionable": positionable,
            }
        )

    subject_stats = {}
    for subject_id, totals in subject_totals.items():
        ranked = sorted(totals, reverse=True)
        subject_stats[subject_id] = {
            "high": max(totals),
            "low": min(totals),
            "avg": money(sum(totals) / len(totals)),
            "positions": _dense_skip_positions(ranked),
        }

    # arm == class in this model (level + arm is one SchoolClass)
    class_avgs = [row["average"] for row in per_student if row["positionable"]]
    class_positions = _dense_skip_positions(sorted(class_avgs, reverse=True))

    sheets = []
    fresh_results = []
    for row in per_student:
        sheet = latest_sheets.get(row["enrollment"].id)
        if sheet is None:
            sheet = ResultSheet.objects.create(
                enrollment=row["enrollment"],
                term=term,
                version=1,
                state=ResultSheet.State.DRAFT,
            )
        if sheet.is_immutable:
            sheets.append(sheet)
            continue
        avg = row["average"]
        pos = class_positions.get(avg) if row["positionable"] else None
        sheet.total_score = row["total"]
        sheet.average = avg
        sheet.position_class = pos
        sheet.position_arm = pos
        sheet.class_size = len(enrollments)
        sheet.arm_size = len(enrollments)
        sheet.subjects_offered = row["offered"]
        sheet.incomplete = row["incomplete"]
        sheet.cumulative_average = _session_average(
            row["enrollment"].student,
            term,
            avg,
            school,
            terms=session_terms,
            known=other_averages.get(row["enrollment"].student_id, {}),
        )
        if term.name == term.Name.THIRD and sheet.cumulative_average is not None:
            if sheet.cumulative_average >= school.pass_threshold:
                sheet.promotion_status = ResultSheet.Promotion.PROMOTED
            else:
                sheet.promotion_status = ResultSheet.Promotion.REPEAT
        dist = defaultdict(int)
        for item in row["subjects"]:
            subject = item["subject"]
            stats = subject_stats.get(subject.id, {})
            positions = stats.get("positions", {})
            total = item["total"]
            label, remark = grade_for(school, school_class.level, percent_of(total, out_of), bands=bands)
            if label:
                dist[label] += 1
            fresh_results.append(
                SubjectResult(
                    result_sheet=sheet,
                    subject=subject,
                    components=item["values"],
                    total=total,
                    grade=label,
                    remark=remark,
                    position=positions.get(total) if total is not None and not item["incomplete"] else None,
                    class_highest=stats.get("high"),
                    class_lowest=stats.get("low"),
                    class_average=stats.get("avg"),
                    incomplete=item["incomplete"],
                )
            )
        sheet.grade_distribution = dict(dist)
        sheet.save()
        sheets.append(sheet)
    mutable = [s for s in sheets if not s.is_immutable]
    SubjectResult.objects.filter(result_sheet__in=mutable).delete()
    SubjectResult.objects.bulk_create(fresh_results)
    return sheets


def _dense_skip_positions(sorted_desc_values):
    """Competition ranking: 1, 2, 2, 4."""
    positions = {}
    last_value = object()
    last_pos = 0
    for index, value in enumerate(sorted_desc_values, start=1):
        if value != last_value:
            last_pos = index
            last_value = value
        positions[value] = last_pos
    return positions


def _other_term_averages(student_ids, terms, current_term):
    """{student_id: {term_id: average}} from each student's latest sheet in the other terms."""
    found = defaultdict(dict)
    other_ids = [t.id for t in terms if t.id != current_term.id]
    if not other_ids:
        return found
    rows = (
        ResultSheet.objects.filter(enrollment__student_id__in=student_ids, term_id__in=other_ids)
        .order_by("-version")
        .values_list("enrollment__student_id", "term_id", "average")
    )
    for student_id, term_id, average in rows:
        found[student_id].setdefault(term_id, average)
    return found


def _session_average(student, term, current_average, school, terms=None, known=None):
    """Average across the session's terms. ``terms`` and ``known`` skip queries when prefetched."""
    if terms is None:
        terms = list(term.session.terms.all())
    if known is None:
        known = _other_term_averages([student.id], terms, term).get(student.id, {})
    averages = []
    weights = []
    default_weights = {"First": Decimal("20"), "Second": Decimal("20"), "Third": Decimal("60")}
    configured = school.term_weights or {}
    for t in terms:
        avg = current_average if t.id == term.id else known.get(t.id)
        if avg is None:
            continue
        averages.append(Decimal(avg))
        weight_key = t.name
        weights.append(Decimal(str(configured.get(weight_key, default_weights.get(t.name, 1)))))
    if not averages:
        return current_average
    if school.average_formula == school.AverageFormula.WEIGHTED and weights:
        total_w = sum(weights)
        if total_w == 0:
            return money(sum(averages) / len(averages))
        return money(sum(a * w for a, w in zip(averages, weights)) / total_w)
    return money(sum(averages) / len(averages))


def snapshot_sheet(sheet):
    school = sheet.school
    enrollment = sheet.enrollment
    student = enrollment.student
    school_class = enrollment.school_class
    term = sheet.term
    ratings = {
        r.trait.name: r.value
        for r in BehaviouralRating.objects.filter(enrollment=enrollment, term=term).select_related("trait")
    }
    comments = {c.author_role: c.body for c in sheet.comments.all()}
    tied_class = (
        ResultSheet.objects.filter(
            enrollment__school_class=school_class,
            term=term,
            version=sheet.version,
            position_class=sheet.position_class,
        ).count()
        > 1
        if sheet.position_class
        else False
    )
    data = {
        "result_code": sheet.result_code,
        "school": {
            "name": school.name,
            "address": school.address,
            "motto": school.motto,
            "phone": school.contact_phone,
            "email": school.contact_email,
            "brand_colour": school.brand_colour,
            "template": school.result_template,
            "show_positions": school.show_positions,
        },
        "student": {
            "name": student.full_name,
            "admission_number": student.admission_number,
            "sex": student.get_sex_display(),
            "class": school_class.name,
            "photo": student.photo.url if student.photo else "",
        },
        "term": {
            "session": term.session.name,
            "name": term.name,
            "resumption": term.resumption_date.isoformat() if term.resumption_date else "",
            "days_opened": term.days_opened,
        },
        "summary": {
            "total": str(sheet.total_score) if sheet.total_score is not None else "",
            "average": str(sheet.average) if sheet.average is not None else "",
            "position": format_position(sheet.position_class, tied_class, school),
            "class_size": sheet.class_size,
            "subjects_offered": sheet.subjects_offered,
            "cumulative_average": str(sheet.cumulative_average) if sheet.cumulative_average is not None else "",
            "promotion": sheet.get_promotion_status_display(),
            "days_present": sheet.days_present,
            "incomplete": sheet.incomplete,
        },
        "subjects": [
            {
                "name": sr.subject.name,
                "components": sr.components,
                "total": str(sr.total) if sr.total is not None else "",
                "grade": sr.grade,
                "remark": sr.remark,
                "position": ordinal(sr.position),
                "class_highest": str(sr.class_highest) if sr.class_highest is not None else "",
                "class_lowest": str(sr.class_lowest) if sr.class_lowest is not None else "",
                "class_average": str(sr.class_average) if sr.class_average is not None else "",
            }
            for sr in sheet.subject_results.select_related("subject")
        ],
        "ratings": ratings,
        "comments": comments,
        "grading_key": _grading_key(school, school_class.level),
    }
    sheet.snapshot = data
    sheet.save(update_fields=["snapshot"])
    return data


def _grading_key(school, level):
    bands = GradeBand.objects.filter(school=school, level=level)
    if not bands.exists():
        bands = GradeBand.objects.filter(school=school, level__isnull=True)
    return [{"label": b.label, "range": f"{b.min_score}-{b.max_score}", "remark": b.remark} for b in bands]
