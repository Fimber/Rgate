"""Small builders for tests. Two schools so tenant isolation can be checked."""

from accounts.models import User
from records.models import ClassTeacherAssignment, Enrollment, Student, SubjectAssignment
from results.models import ClassCycle, ResultSheet, Score
from results.services.compute import recompute_class, snapshot_sheet
from schools.models import (
    AcademicSession,
    AssessmentComponent,
    GradeBand,
    Level,
    LevelSubject,
    School,
    SchoolClass,
    Subject,
    Term,
)

PASSWORD = "secret-pass-123"
_phone_counter = [8030000000]


def next_phone():
    _phone_counter[0] += 1
    return f"0{_phone_counter[0]}"


def make_user(school, role, **extra):
    return User.objects.create_user(
        phone=extra.pop("phone", None) or next_phone(),
        password=PASSWORD,
        first_name=extra.pop("first_name", role.title()),
        last_name=extra.pop("last_name", school.slug if school else "hq"),
        role=role,
        school=school,
        **extra,
    )


class SchoolWorld:
    """A complete, scored school: one class, two subjects, two components."""

    def __init__(self, slug, students=3):
        self.school = School.objects.create(name=f"{slug.title()} College", slug=slug, setup_complete=True)
        self.session = AcademicSession.objects.create(school=self.school, name="2025/2026", is_current=True)
        self.term = Term.objects.create(session=self.session, name=Term.Name.FIRST, is_current=True)
        self.level = Level.objects.create(school=self.school, name="JSS 1", order=1)
        self.classroom = SchoolClass.objects.create(school=self.school, level=self.level, arm="A", name="JSS 1 A")
        self.english = Subject.objects.create(school=self.school, name="English Language")
        self.maths = Subject.objects.create(school=self.school, name="Mathematics")
        for subject in (self.english, self.maths):
            LevelSubject.objects.create(level=self.level, subject=subject, is_core=True)
        self.ca = AssessmentComponent.objects.create(
            school=self.school, session=self.session, name="CA", max_score=40, order=1
        )
        self.exam = AssessmentComponent.objects.create(
            school=self.school, session=self.session, name="Exam", max_score=60, order=2
        )
        GradeBand.objects.create(school=self.school, min_score=70, max_score=100, label="A", remark="Excellent")
        GradeBand.objects.create(school=self.school, min_score=0, max_score=69.99, label="C", remark="Credit")

        self.admin = make_user(self.school, User.Role.SCHOOL_ADMIN)
        self.head = make_user(self.school, User.Role.HEAD_OF_SCHOOL)
        self.class_teacher = make_user(self.school, User.Role.CLASS_TEACHER)
        self.teacher = make_user(self.school, User.Role.SUBJECT_TEACHER)
        self.other_teacher = make_user(self.school, User.Role.SUBJECT_TEACHER)
        self.parent = make_user(self.school, User.Role.PARENT)

        self.assignment = SubjectAssignment.objects.create(
            teacher=self.teacher,
            subject=self.english,
            school_class=self.classroom,
            session=self.session,
            term=self.term,
        )
        self.maths_assignment = SubjectAssignment.objects.create(
            teacher=self.other_teacher,
            subject=self.maths,
            school_class=self.classroom,
            session=self.session,
            term=self.term,
        )
        ClassTeacherAssignment.objects.create(
            teacher=self.class_teacher, school_class=self.classroom, session=self.session, term=self.term
        )

        self.enrollments = []
        for index in range(students):
            student = Student.objects.create(
                school=self.school,
                admission_number=f"{slug.upper()}/{index + 1:03d}",
                surname=f"Surname{index}",
                first_name=f"First{index}",
                sex="F" if index % 2 else "M",
                parent_user=self.parent if index == 0 else None,
                parent_phone="08099990000" if index == 0 else "",
            )
            self.enrollments.append(
                Enrollment.objects.create(
                    student=student, school_class=self.classroom, session=self.session, term=self.term
                )
            )
        self.student = self.enrollments[0].student if self.enrollments else None

    def score_everything(self):
        for offset, enrollment in enumerate(self.enrollments):
            for subject in (self.english, self.maths):
                Score.objects.update_or_create(
                    enrollment=enrollment,
                    subject=subject,
                    component=self.ca,
                    defaults={"value": 30 - offset, "updated_by": self.teacher},
                )
                Score.objects.update_or_create(
                    enrollment=enrollment,
                    subject=subject,
                    component=self.exam,
                    defaults={"value": 50 - offset, "updated_by": self.teacher},
                )

    def publish(self):
        """Score, compute and mark every sheet published without the HTTP flow."""
        self.score_everything()
        sheets = recompute_class(self.classroom, self.term)
        for index, sheet in enumerate(sheets):
            sheet.state = ResultSheet.State.PUBLISHED
            sheet.result_code = f"{self.school.slug.upper()}{index:04d}"
            sheet.save()
            snapshot_sheet(sheet)
        ClassCycle.objects.update_or_create(
            school_class=self.classroom, term=self.term, defaults={"state": ClassCycle.State.PUBLISHED}
        )
        return sheets

    def url(self, path):
        return f"/{self.school.slug}/{path.lstrip('/')}"
