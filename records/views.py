import re
import secrets
from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from common.audit import log_action
from common.parsing import to_int
from common.tenancy import STAFF_ROLES, school_admin_required, school_staff_required
from common.uploads import clean_image
from records.models import ClassTeacherAssignment, Enrollment, Student, SubjectAssignment
from records.services import enroll_active_students, import_students, student_template
from schools.models import LevelSubject, SchoolClass, Subject

MAX_IMPORT_BYTES = 5 * 1024 * 1024
PHONE_RE = re.compile(r"^0[7-9][01]\d{8}$")


@school_staff_required
def students(request):
    school = request.school
    term = school.current_term()
    qs = school.students.all()
    query = (request.GET.get("q") or "").strip()
    if query:
        qs = qs.filter(
            Q(surname__icontains=query) | Q(first_name__icontains=query) | Q(admission_number__icontains=query)
        )
    return render(
        request,
        "records/students.html",
        {"students": qs.select_related("parent_user")[:400], "query": query, "term": term},
    )


def _apply_student_form(student, data):
    """Copy posted fields onto ``student``; return a list of human-readable problems."""
    errors = []
    student.admission_number = (data.get("admission_number") or "").strip()
    student.surname = (data.get("surname") or "").strip()
    student.first_name = (data.get("first_name") or "").strip()
    student.other_names = (data.get("other_names") or "").strip()
    student.sex = data.get("sex") or ""
    student.parent_name = (data.get("parent_name") or "").strip()
    phone = (data.get("parent_phone") or "").strip()
    student.parent_phone = User.objects.normalize_phone(phone) if phone else ""
    student.parent_email = (data.get("parent_email") or "").strip()
    student.status = data.get("status") or Student.Status.ACTIVE
    if not student.admission_number:
        errors.append("Admission number is required.")
    if not student.surname or not student.first_name:
        errors.append("Surname and first name are required.")
    if student.sex not in Student.Sex.values:
        errors.append("Choose male or female.")
    if student.status not in Student.Status.values:
        errors.append("Choose a valid status.")
    if student.parent_phone and not PHONE_RE.match(student.parent_phone):
        errors.append("Parent phone should look like 08031234567.")
    raw_dob = (data.get("date_of_birth") or "").strip()
    if raw_dob:
        try:
            student.date_of_birth = date.fromisoformat(raw_dob)
        except ValueError:
            errors.append("Date of birth should be a date.")
    clash = Student.objects.filter(school=student.school, admission_number__iexact=student.admission_number)
    if student.pk:
        clash = clash.exclude(pk=student.pk)
    if student.admission_number and clash.exists():
        errors.append(f"Another student already has admission number {student.admission_number}.")
    return errors


@school_admin_required
def student_edit(request, pk=None):
    school = request.school
    student = get_object_or_404(Student, pk=pk, school=school) if pk else None
    term = school.current_term()
    current = student.current_enrollment(term) if student and term else None
    if request.method == "POST":
        if student is None:
            student = Student(school=school)
        errors = _apply_student_form(student, request.POST)
        if request.FILES.get("photo"):
            try:
                student.photo = clean_image(request.FILES["photo"])
            except ValidationError as exc:
                errors.extend(exc.messages)
        school_class = None
        class_id = request.POST.get("school_class")
        if class_id and term:
            school_class = SchoolClass.objects.filter(pk=class_id, school=school).first()
            if school_class is None:
                errors.append("Choose a class in this school.")
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            student.save()
            if school_class:
                Enrollment.objects.update_or_create(
                    student=student,
                    term=term,
                    defaults={
                        "school_class": school_class,
                        "session": term.session,
                        "status": Enrollment.Status.ACTIVE,
                    },
                )
            messages.success(request, "Student saved.")
            return redirect("records:students")
    return render(
        request,
        "records/student_form.html",
        {
            "student": student,
            "classes": school.classes.select_related("level"),
            "term": term,
            "current_class_id": current.school_class_id if current else None,
            "statuses": Student.Status.choices,
        },
    )


@school_admin_required
def student_import(request):
    school = request.school
    term = school.current_term()
    result = None
    if request.method == "POST" and request.FILES.get("file"):
        upload = request.FILES["file"]
        if upload.size > MAX_IMPORT_BYTES:
            messages.error(request, "That file is larger than 5 MB.")
        else:
            try:
                result = import_students(school, upload, term.session if term else None, term)
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Imported {result['created']} new students, updated {result['updated']}. "
                    f"{len(result['errors'])} row(s) had issues.",
                )
    return render(request, "records/import.html", {"result": result})


@school_staff_required
def student_template_download(request):
    buffer = student_template()
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="regate-students-template.xlsx"'
    return response


def temporary_password():
    """Readable one-time password: staff are forced to change it at first sign-in."""
    return f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"


TEACHING_ROLES = (User.Role.SUBJECT_TEACHER, User.Role.CLASS_TEACHER)


def _teaching_rows(school, data):
    """Pair up the posted class and subject lists. Returns (rows, problems).

    Each row is (SchoolClass, typed subject name). Wholly blank rows are ignored.
    """
    rows, problems = [], []
    for class_id, subject_name in zip(data.getlist("teach_class"), data.getlist("teach_subject")):
        subject_name = " ".join((subject_name or "").split())
        if not class_id and not subject_name:
            continue
        school_class = SchoolClass.objects.filter(pk=to_int(class_id), school=school).first() if class_id else None
        if school_class is None:
            problems.append(f"Choose the class for {subject_name or 'each subject'}.")
        elif not subject_name:
            problems.append(f"Type the subject they will take in {school_class}.")
        else:
            rows.append((school_class, subject_name))
    return rows, problems


@school_staff_required
def staff_list(request):
    school = request.school
    term = school.current_term()
    classes = list(school.classes.select_related("level").order_by("level__order", "arm"))
    posted = {}
    if request.method == "POST":
        if not request.user.is_school_admin_like:
            messages.error(request, "Only a school admin can add staff.")
            return redirect("records:staff")
        data = request.POST
        role = data.get("role") or User.Role.SUBJECT_TEACHER
        phone = User.objects.normalize_phone(data.get("phone") or "")
        first = (data.get("first_name") or "").strip()
        last = (data.get("last_name") or "").strip()
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        rows, problems = _teaching_rows(school, data) if role in TEACHING_ROLES else ([], [])
        form_class = None
        if role == User.Role.CLASS_TEACHER and data.get("form_class"):
            form_class = SchoolClass.objects.filter(pk=to_int(data.get("form_class")), school=school).first()
            if form_class is None:
                problems.append("Choose the class they will be class teacher for.")
        if role not in STAFF_ROLES:
            problems.insert(0, "Choose a staff role.")
        if not first or not last:
            problems.insert(0, "First and last name are required.")
        if not PHONE_RE.match(phone):
            problems.append("Enter an 11-digit Nigerian phone number, like 08031234567.")
        elif User.objects.filter(phone=phone).exists() or (email and User.objects.filter(email__iexact=email).exists()):
            problems.append("Someone already uses that phone number or email.")
        if password and len(password) < 8:
            problems.append("A password must be at least 8 characters. Leave it blank to generate one.")
        if (rows or form_class) and term is None:
            problems.append("Set the current term before giving staff classes and subjects.")
        if not problems:
            generated = not password
            password = password or temporary_password()
            with transaction.atomic():
                user = User.objects.create_user(
                    phone=phone,
                    password=password,
                    first_name=first,
                    last_name=last,
                    email=email,
                    role=role,
                    school=school,
                    must_change_password=True,
                )
                taught = []
                for school_class, subject_name in rows:
                    subject, _ = subject_from_typed_name(school, school_class, subject_name)
                    SubjectAssignment.objects.get_or_create(
                        teacher=user, subject=subject, school_class=school_class, session=term.session, term=term
                    )
                    taught.append(f"{subject} in {school_class}")
                if form_class:
                    ClassTeacherAssignment.objects.update_or_create(
                        school_class=form_class, term=term, defaults={"teacher": user, "session": term.session}
                    )
                log_action(
                    request,
                    "create_staff",
                    "user",
                    user,
                    after={"role": role, "phone": phone, "teaches": taught, "class_teacher_of": str(form_class or "")},
                )
            summary = f"{user.get_full_name()} added"
            if taught:
                summary += " to teach " + "; ".join(taught)
            if form_class:
                summary += f", and is class teacher for {form_class}"
            summary += "."
            if generated:
                summary += f" Temporary password: {password} — share it privately."
            messages.success(request, summary + " They must change the password at first sign-in.")
            return redirect("records:staff")
        for problem in problems:
            messages.error(request, problem)
        # Keep what was typed so a long list of classes is not lost to one mistake.
        posted = {
            "first_name": first,
            "last_name": last,
            "phone": data.get("phone") or "",
            "email": email,
            "role": role,
            "form_class": to_int(data.get("form_class")),
            "rows": [
                {"class_id": to_int(c), "subject": sub}
                for c, sub in zip(data.getlist("teach_class"), data.getlist("teach_subject"))
                if c or sub.strip()
            ],
        }
    staff = list(school.users.filter(role__in=STAFF_ROLES).order_by("last_name", "first_name"))
    if term:
        teaching = {}
        for a in SubjectAssignment.objects.filter(term=term, teacher__in=staff).select_related(
            "subject", "school_class"
        ):
            teaching.setdefault(a.teacher_id, []).append(f"{a.subject} ({a.school_class})")
        forms = {a.teacher_id: a.school_class for a in ClassTeacherAssignment.objects.filter(term=term)}
        for person in staff:
            person.teaching = teaching.get(person.id, [])
            person.form_class = forms.get(person.id)
    return render(
        request,
        "records/staff.html",
        {
            "staff": staff,
            "term": term,
            "classes": classes,
            "subjects": school.subjects.order_by("name"),
            "roles": [
                (r, User.Role(r).label) for r in ("subject_teacher", "class_teacher", "head_of_school", "school_admin")
            ],
            "posted": posted,
            "rows": posted.get("rows") or [{"class_id": None, "subject": ""}],
        },
    )


def subject_from_typed_name(school, school_class, typed):
    """Find the school's subject by name (any case or spacing) or create it.

    The subject is also attached to the class's level so it appears on results. A subject
    added this way is not core, so a pupil who does not take it is never marked incomplete.
    Returns (subject, created) or (None, False) for a blank name.
    """
    name = " ".join((typed or "").split())[:120]
    if not name:
        return None, False
    subject = Subject.objects.filter(school=school, name__iexact=name).first()
    created = subject is None
    if created:
        subject = Subject.objects.create(school=school, name=name)
    LevelSubject.objects.get_or_create(level=school_class.level, subject=subject, defaults={"is_core": False})
    return subject, created


@school_staff_required
def assignments(request):
    school = request.school
    term = school.current_term()
    if request.method == "POST":
        if not request.user.is_school_admin_like:
            messages.error(request, "Only the principal or a school admin can assign subjects.")
            return redirect("records:assignments")
        if term is None:
            messages.error(request, "Set the current term first.")
            return redirect("records:assignments")
        action = request.POST.get("action")
        if action == "remove_subject":
            assignment = get_object_or_404(
                SubjectAssignment, pk=to_int(request.POST.get("assignment")), school_class__school=school
            )
            log_action(
                request,
                "unassign_subject",
                "subject_assignment",
                assignment,
                before={"teacher": assignment.teacher_id, "subject": assignment.subject.name},
            )
            messages.success(request, f"{assignment.subject} removed from {assignment.teacher.get_full_name()}.")
            assignment.delete()
            return redirect("records:assignments")
        teacher = get_object_or_404(User, pk=to_int(request.POST.get("teacher")), school=school, role__in=STAFF_ROLES)
        school_class = get_object_or_404(SchoolClass, pk=to_int(request.POST.get("school_class")), school=school)
        if action == "subject":
            subject, created = subject_from_typed_name(school, school_class, request.POST.get("subject_name"))
            if subject is None:
                messages.error(request, "Type the subject the teacher will take.")
                return redirect("records:assignments")
            assignment, is_new = SubjectAssignment.objects.get_or_create(
                teacher=teacher, subject=subject, school_class=school_class, session=term.session, term=term
            )
            if not is_new:
                messages.info(request, f"{teacher.get_full_name()} already takes {subject} in {school_class}.")
                return redirect("records:assignments")
            log_action(
                request,
                "assign_subject",
                "subject_assignment",
                assignment,
                after={"teacher": teacher.id, "subject": subject.name, "class": school_class.name},
            )
            note = " It is a new subject, added to the school's list." if created else ""
            messages.success(request, f"{teacher.get_full_name()} now takes {subject} in {school_class}.{note}")
        elif action == "class_teacher":
            ClassTeacherAssignment.objects.update_or_create(
                school_class=school_class,
                term=term,
                defaults={"teacher": teacher, "session": term.session},
            )
            messages.success(request, f"{teacher.get_full_name()} is now class teacher for {school_class}.")
        return redirect("records:assignments")
    return render(
        request,
        "records/assignments.html",
        {
            "term": term,
            "teachers": school.users.filter(role__in=STAFF_ROLES, is_active=True),
            "classes": school.classes.select_related("level"),
            "subjects": school.subjects.order_by("name"),
            "subject_assignments": SubjectAssignment.objects.filter(term=term)
            .select_related("teacher", "subject", "school_class")
            .order_by("school_class__name", "subject__name")
            if term
            else [],
            "class_teachers": ClassTeacherAssignment.objects.filter(term=term).select_related("teacher", "school_class")
            if term
            else [],
        },
    )


@school_staff_required
def my_classes(request):
    """Teachers add or drop the classes and subjects they teach, when the school allows it."""
    school = request.school
    term = school.current_term()
    user = request.user
    allowed = school.teachers_self_assign and term is not None
    if request.method == "POST":
        if not allowed:
            messages.error(request, "Your school assigns classes for you. Ask the principal.")
            return redirect("records:my_classes")
        action = request.POST.get("action")
        if action == "drop":
            assignment = get_object_or_404(
                SubjectAssignment, pk=to_int(request.POST.get("assignment")), teacher=user, term=term
            )
            log_action(
                request,
                "self_unassign",
                "subject_assignment",
                assignment,
                before={"subject": assignment.subject.name, "class": assignment.school_class.name},
            )
            messages.success(request, f"You no longer take {assignment.subject} in {assignment.school_class}.")
            assignment.delete()
            return redirect("records:my_classes")
        if action == "form_class" and user.role == User.Role.CLASS_TEACHER:
            school_class = get_object_or_404(SchoolClass, pk=to_int(request.POST.get("form_class")), school=school)
            current = ClassTeacherAssignment.objects.filter(school_class=school_class, term=term).first()
            if current and current.teacher_id != user.id:
                messages.error(
                    request,
                    f"{current.teacher.get_full_name()} is already class teacher for {school_class}. Ask the principal.",
                )
            else:
                ClassTeacherAssignment.objects.update_or_create(
                    school_class=school_class, term=term, defaults={"teacher": user, "session": term.session}
                )
                log_action(request, "self_class_teacher", "class", school_class)
                messages.success(request, f"You are class teacher for {school_class}.")
            return redirect("records:my_classes")
        rows, problems = _teaching_rows(school, request.POST)
        known = {s.name.lower(): s for s in school.subjects.all()}
        plan = []
        for school_class, subject_name in rows:
            subject = known.get(subject_name.lower())
            if subject is None:
                problems.append(
                    f"{subject_name} is not one of the school's subjects. Pick from the list, or ask the principal to add it."
                )
                continue
            taken = (
                SubjectAssignment.objects.filter(subject=subject, school_class=school_class, term=term)
                .exclude(teacher=user)
                .select_related("teacher")
                .first()
            )
            if taken:
                problems.append(
                    f"{subject} in {school_class} is taken by {taken.teacher.get_full_name()}. Ask the principal to change it."
                )
                continue
            plan.append((school_class, subject))
        if not rows and not problems:
            problems.append("Choose a class and a subject.")
        if problems:
            for problem in problems:
                messages.error(request, problem)
        else:
            added = []
            with transaction.atomic():
                for school_class, subject in plan:
                    LevelSubject.objects.get_or_create(
                        level=school_class.level, subject=subject, defaults={"is_core": False}
                    )
                    assignment, created = SubjectAssignment.objects.get_or_create(
                        teacher=user, subject=subject, school_class=school_class, session=term.session, term=term
                    )
                    if created:
                        added.append(f"{subject} in {school_class}")
                        log_action(
                            request,
                            "self_assign",
                            "subject_assignment",
                            assignment,
                            after={"subject": subject.name, "class": school_class.name},
                        )
            if added:
                messages.success(request, "Added " + "; ".join(added) + ". They are on your Score entry list now.")
            else:
                messages.info(request, "You already take those.")
            return redirect("records:my_classes")
    mine = (
        SubjectAssignment.objects.filter(teacher=user, term=term)
        .select_related("subject", "school_class")
        .order_by("school_class__name", "subject__name")
        if term
        else []
    )
    form_class = ClassTeacherAssignment.objects.filter(teacher=user, term=term).select_related("school_class").first()
    free_classes = []
    if term and user.role == User.Role.CLASS_TEACHER and not form_class:
        taken_ids = ClassTeacherAssignment.objects.filter(term=term).values_list("school_class_id", flat=True)
        free_classes = school.classes.exclude(id__in=taken_ids).order_by("name")
    return render(
        request,
        "records/my_classes.html",
        {
            "term": term,
            "allowed": allowed,
            "mine": mine,
            "form_class": form_class,
            "free_classes": free_classes,
            "classes": school.classes.select_related("level").order_by("level__order", "arm"),
            "subjects": school.subjects.order_by("name"),
            "rows": [{"class_id": None, "subject": ""}],
        },
    )


@school_admin_required
def school_export(request):
    from io import BytesIO

    from openpyxl import Workbook

    from results.models import ResultSheet

    book = Workbook()
    students_sheet = book.active
    students_sheet.title = "Students"
    students_sheet.append(["admission_number", "name", "sex", "status", "parent_name", "parent_phone"])
    for student in request.school.students.all():
        students_sheet.append(
            [
                student.admission_number,
                student.full_name,
                student.sex,
                student.status,
                student.parent_name,
                student.parent_phone,
            ]
        )
    results_sheet = book.create_sheet("Published results")
    results_sheet.append(["admission_number", "term", "average", "position", "result_code", "state"])
    for sheet in ResultSheet.objects.filter(enrollment__student__school=request.school).select_related(
        "enrollment__student", "term", "term__session"
    ):
        results_sheet.append(
            [
                sheet.enrollment.student.admission_number,
                str(sheet.term),
                float(sheet.average) if sheet.average is not None else "",
                sheet.position_class,
                sheet.result_code or "",
                sheet.state,
            ]
        )
    log_action(request, "export_school", "school", request.school)
    buffer = BytesIO()
    book.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{request.school.slug}-export.xlsx"'
    return response


@school_admin_required
@require_POST
def carry_enrollments(request):
    school = request.school
    term = school.current_term()
    if term:
        count = enroll_active_students(school, term.session, term)
        messages.success(request, f"Enrolled {count} students into {term}.")
    return redirect("records:students")
