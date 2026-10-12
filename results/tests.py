from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from records.models import Enrollment, Student
from results.models import Score
from results.services.compute import _dense_skip_positions, recompute_class
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


class RankingTests(TestCase):
    def test_ties_skip_the_next_place(self):
        ranks = _dense_skip_positions([Decimal("80"), Decimal("80"), Decimal("70")])
        self.assertEqual(ranks[Decimal("80")], 1)
        self.assertEqual(ranks[Decimal("70")], 3)


class ComputeTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="Test School",
            slug="test",
            setup_complete=True,
            tie_display=School.TieDisplay.POSITION_TIE,
            incomplete_rule=School.IncompleteRule.BLOCK,
        )
        self.session = AcademicSession.objects.create(school=self.school, name="2025/2026", is_current=True)
        self.term = Term.objects.create(session=self.session, name=Term.Name.FIRST, is_current=True)
        self.level = Level.objects.create(school=self.school, name="JSS 1", order=1)
        self.classroom = SchoolClass.objects.create(school=self.school, level=self.level, arm="A", name="JSS 1 A")
        self.english = Subject.objects.create(school=self.school, name="English Language")
        self.maths = Subject.objects.create(school=self.school, name="Mathematics")
        LevelSubject.objects.create(level=self.level, subject=self.english, is_core=True)
        LevelSubject.objects.create(level=self.level, subject=self.maths, is_core=True)
        self.ca = AssessmentComponent.objects.create(
            school=self.school, session=self.session, name="CA1", max_score=40, order=1
        )
        self.exam = AssessmentComponent.objects.create(
            school=self.school, session=self.session, name="Exam", max_score=60, order=2
        )
        GradeBand.objects.create(school=self.school, min_score=70, max_score=100, label="A", remark="Excellent")
        GradeBand.objects.create(school=self.school, min_score=0, max_score=69.99, label="C", remark="Credit")
        self.teacher = User.objects.create_user(
            phone="08011110000",
            password="secret123",
            first_name="T",
            last_name="Eacher",
            role=User.Role.SUBJECT_TEACHER,
            school=self.school,
        )

    def _student(self, number, scores):
        student = Student.objects.create(
            school=self.school, admission_number=number, surname=number, first_name="A", sex="F"
        )
        enrollment = Enrollment.objects.create(
            student=student, school_class=self.classroom, session=self.session, term=self.term
        )
        for subject, component, value, marker in scores:
            Score.objects.create(
                enrollment=enrollment,
                subject=subject,
                component=component,
                value=value,
                marker=marker,
                updated_by=self.teacher,
            )
        return enrollment

    def test_positions_and_incomplete_flag(self):
        self._student(
            "001",
            [
                (self.english, self.ca, 32, Score.Marker.SCORE),
                (self.english, self.exam, 50, Score.Marker.SCORE),
                (self.maths, self.ca, 30, Score.Marker.SCORE),
                (self.maths, self.exam, 48, Score.Marker.SCORE),
            ],
        )
        self._student(
            "002",
            [
                (self.english, self.ca, 32, Score.Marker.SCORE),
                (self.english, self.exam, 50, Score.Marker.SCORE),
                (self.maths, self.ca, 30, Score.Marker.SCORE),
                (self.maths, self.exam, 48, Score.Marker.SCORE),
            ],
        )
        incomplete = self._student(
            "003",
            [
                (self.english, self.ca, 10, Score.Marker.SCORE),
                (self.english, self.exam, 20, Score.Marker.SCORE),
            ],
        )
        sheets = {s.enrollment.student.admission_number: s for s in recompute_class(self.classroom, self.term)}
        self.assertEqual(sheets["001"].position_class, 1)
        self.assertEqual(sheets["002"].position_class, 1)
        self.assertTrue(sheets["003"].incomplete)
        self.assertIsNone(sheets["003"].position_class)
        self.assertEqual(sheets["001"].subject_results.get(subject=self.english).grade, "A")
        # mid-term exempt should not crash
        incomplete.joined_after_components = [self.ca.id]
        incomplete.save()
        recompute_class(self.classroom, self.term)
