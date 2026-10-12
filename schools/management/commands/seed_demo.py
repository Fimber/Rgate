from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from portal.models import FeeFlag, ResultPin
from records.models import ClassTeacherAssignment, Enrollment, Student, SubjectAssignment
from results.models import BehaviouralRating, Comment, Score, SubjectSheet
from results.services.compute import recompute_class, snapshot_sheet
from results.services.pdf import generate_result_pdf
from results.services.workflow import get_cycle
from schools.models import BehaviouralTrait, LevelSubject, School, SchoolClass, Term
from schools.services import apply_nigerian_defaults, ensure_current_calendar

STUDENTS = [
    ("GFC/001", "Nnamdi", "Adaeze", "Chioma", "F", "Ngozi Nnamdi", "08055555501", 88),
    ("GFC/002", "Okafor", "Chinedu", "Ikechukwu", "M", "Ifeanyi Okafor", "08055555502", 88),
    ("GFC/003", "Bello", "Fatima", "Aisha", "F", "Musa Bello", "08055555503", 74),
    ("GFC/004", "Hart", "Emmanuel", "Tamuno", "M", "Grace Hart", "08055555504", 67),
    ("GFC/005", "Wokoma", "Blessing", "", "F", "Joy Wokoma", "08055555505", 59),
    ("GFC/006", "Yusuf", "Ibrahim", "Sani", "M", "Amina Yusuf", "08055555506", 51),
    ("GFC/007", "Amadi", "Precious", "Onyinye", "F", "Ngozi Nnamdi", "08055555501", 43),
    ("GFC/008", "George", "Tamarabrakemi", "", "F", "Sotonye George", "08055555508", 38),
]


class Command(BaseCommand):
    help = "Load Greenfield College, a Port Harcourt pilot school, with a live term."

    def handle(self, *args, **options):
        platform, _ = User.objects.get_or_create(
            phone="08000000000",
            defaults={
                "first_name": "CSS",
                "last_name": "Nkpolu",
                "role": User.Role.PLATFORM_ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "email": "hq@regate.ng",
            },
        )
        platform.set_password("admin1234")
        platform.is_staff = True
        platform.is_superuser = True
        platform.role = User.Role.PLATFORM_ADMIN
        platform.save()

        school, _ = School.objects.get_or_create(
            slug="greenfield",
            defaults={
                "name": "Greenfield College",
                "address": "Nkpolu-Oroworukwo, Port Harcourt, Rivers State",
                "motto": "Knowledge and Character",
                "contact_phone": "08011111111",
                "contact_email": "office@greenfield.sch.ng",
                "brand_colour": "#0B3D2E",
                "bursary_contact": "Bursary: 08011111111",
                "setup_complete": True,
                "portal_mode": School.PortalMode.BOTH,
                "tie_display": School.TieDisplay.POSITION_TIE,
            },
        )
        school.setup_complete = True
        school.save()

        session = ensure_current_calendar(school, "2025/2026")
        apply_nigerian_defaults(school, session)
        term = session.terms.get(name=Term.Name.FIRST)
        term.start_date = date(2025, 9, 8)
        term.end_date = date(2025, 12, 12)
        term.resumption_date = date(2026, 1, 12)
        term.days_opened = 68
        term.is_current = True
        term.save()
        session.terms.exclude(pk=term.pk).update(is_current=False)

        staff = {
            "admin": ("08011111111", "Ada", "Kalu", User.Role.SCHOOL_ADMIN, "school1234"),
            "head": ("08022222222", "Promise", "Wike", User.Role.HEAD_OF_SCHOOL, "head1234"),
            "class": ("08033333333", "Ruth", "Amadi", User.Role.CLASS_TEACHER, "teacher1234"),
            "subject": ("08044444444", "Daniel", "Ofori", User.Role.SUBJECT_TEACHER, "teacher1234"),
        }
        users = {}
        for key, (phone, first, last, role, password) in staff.items():
            user, _ = User.objects.get_or_create(
                phone=phone,
                defaults={"first_name": first, "last_name": last, "role": role, "school": school},
            )
            user.set_password(password)
            user.role = role
            user.school = school
            user.save()
            users[key] = user

        jss1 = school.levels.get(name="JSS 1")
        classroom = SchoolClass.objects.get(school=school, level=jss1, arm="A")
        subjects = [ls.subject for ls in LevelSubject.objects.filter(level=jss1)]
        ClassTeacherAssignment.objects.update_or_create(
            school_class=classroom, term=term, defaults={"teacher": users["class"], "session": session}
        )
        for subject in subjects:
            SubjectAssignment.objects.get_or_create(
                teacher=users["subject"],
                subject=subject,
                school_class=classroom,
                session=session,
                term=term,
            )

        parent_users = {}
        created_students = []
        for number, surname, first, other, sex, parent_name, parent_phone, _avg in STUDENTS:
            parent = parent_users.get(parent_phone)
            if parent is None:
                parent, _ = User.objects.get_or_create(
                    phone=parent_phone,
                    defaults={
                        "first_name": parent_name.split()[0],
                        "last_name": surname,
                        "role": User.Role.PARENT,
                        "school": school,
                    },
                )
                parent.set_password("parent1234")
                parent.role = User.Role.PARENT
                parent.school = school
                parent.save()
                parent_users[parent_phone] = parent
            student, _ = Student.objects.update_or_create(
                school=school,
                admission_number=number,
                defaults={
                    "surname": surname,
                    "first_name": first,
                    "other_names": other,
                    "sex": sex,
                    "parent_name": parent_name,
                    "parent_phone": parent_phone,
                    "parent_user": parent,
                    "status": Student.Status.ACTIVE,
                    "admission_date": date(2024, 9, 9),
                },
            )
            Enrollment.objects.get_or_create(
                student=student,
                term=term,
                defaults={"school_class": classroom, "session": session, "status": Enrollment.Status.ACTIVE},
            )
            created_students.append(student)

        student_user, _ = User.objects.get_or_create(
            phone="08066666666",
            defaults={
                "first_name": "Adaeze",
                "last_name": "Nnamdi",
                "role": User.Role.STUDENT,
                "school": school,
            },
        )
        student_user.set_password("student1234")
        student_user.role = User.Role.STUDENT
        student_user.school = school
        student_user.save()
        created_students[0].student_user = student_user
        created_students[0].save(update_fields=["student_user"])

        components = list(session.components.all())
        traits = list(school.traits.exclude(domain=BehaviouralTrait.Domain.SKILL))
        for student, row in zip(created_students, STUDENTS):
            target = row[7]
            enrollment = student.enrollments.get(term=term)
            for subject in subjects:
                for component in components:
                    value = min(component.max_score, max(0, round(target * component.max_score / 100)))
                    Score.objects.update_or_create(
                        enrollment=enrollment,
                        subject=subject,
                        component=component,
                        defaults={
                            "value": Decimal(value),
                            "marker": Score.Marker.SCORE,
                            "updated_by": users["subject"],
                        },
                    )
            for trait in traits:
                BehaviouralRating.objects.update_or_create(
                    enrollment=enrollment,
                    term=term,
                    trait=trait,
                    defaults={"value": 5 if target >= 70 else 4 if target >= 50 else 3},
                )
        for subject in subjects:
            SubjectSheet.objects.update_or_create(
                school_class=classroom,
                subject=subject,
                term=term,
                defaults={
                    "state": SubjectSheet.State.SUBMITTED,
                    "submitted_by": users["subject"],
                    "submitted_at": timezone.now(),
                },
            )

        sheets = recompute_class(classroom, term)
        cycle = get_cycle(classroom, term)
        cycle.state = cycle.State.APPROVED
        cycle.reviewed_by = users["class"]
        cycle.approved_by = users["head"]
        cycle.reviewed_at = timezone.now()
        cycle.approved_at = timezone.now()
        cycle.save()

        for sheet in sheets:
            sheet.days_present = 64 if sheet.enrollment.student.admission_number != "GFC/008" else 51
            sheet.state = sheet.State.APPROVED
            sheet.save()
            Comment.objects.update_or_create(
                result_sheet=sheet,
                author_role=Comment.AuthorRole.CLASS_TEACHER,
                defaults={"body": "A consistent term. Continue this way.", "author": users["class"]},
            )
            Comment.objects.update_or_create(
                result_sheet=sheet,
                author_role=Comment.AuthorRole.HEAD_OF_SCHOOL,
                defaults={"body": "The school commends this effort.", "author": users["head"]},
            )

        # Publish everyone except the debtor so fee gating is visible
        for sheet in sheets:
            student = sheet.enrollment.student
            if student.admission_number == "GFC/008":
                FeeFlag.objects.update_or_create(
                    student=student,
                    term=term,
                    defaults={
                        "status": FeeFlag.Status.OWING,
                        "reason": "Second term balance",
                        "set_by": users["admin"],
                    },
                )
            else:
                FeeFlag.objects.update_or_create(
                    student=student,
                    term=term,
                    defaults={"status": FeeFlag.Status.CLEARED, "set_by": users["admin"]},
                )
            sheet.result_code = sheet.result_code or f"GF{student.admission_number[-3:]}"
            sheet.state = sheet.State.PUBLISHED
            sheet.published_at = timezone.now()
            sheet.published_by = users["admin"]
            sheet.save()
            snapshot_sheet(sheet)
            generate_result_pdf(sheet)

        ResultPin.objects.get_or_create(
            school=school,
            code="DEMO1234",
            defaults={
                "student": created_students[0],
                "term": term,
                "uses_remaining": 5,
                "max_uses": 5,
                "batch_label": "pilot",
                "created_by": users["admin"],
            },
        )

        self.stdout.write(self.style.SUCCESS("Greenfield College is ready."))
        self.stdout.write("Platform  08000000000 / admin1234")
        self.stdout.write("Admin     08011111111 / school1234")
        self.stdout.write("Head      08022222222 / head1234")
        self.stdout.write("Teacher   08033333333 or 08044444444 / teacher1234")
        self.stdout.write("Parent    08055555501 / parent1234  (Adaeze + Precious)")
        self.stdout.write("Student   08066666666 / student1234")
        self.stdout.write("PIN       GFC/001 + DEMO1234")
        self.stdout.write("Debtor    GFC/008 Tamarabrakemi George is owing")
