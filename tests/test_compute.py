from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from results.models import ResultSheet, Score
from results.services.compute import format_position, ordinal, recompute_class
from results.services.pdf import latin_safe
from schools.models import School, Term
from tests.factories import SchoolWorld


class ComputeBehaviourTests(TestCase):
    def setUp(self):
        self.world = SchoolWorld("calc", students=4)

    def test_totals_averages_and_competition_ranking(self):
        self.world.score_everything()
        sheets = {s.enrollment_id: s for s in recompute_class(self.world.classroom, self.world.term)}
        first = sheets[self.world.enrollments[0].id]
        # 30 + 50 per subject, two subjects
        self.assertEqual(first.total_score, Decimal("160.00"))
        self.assertEqual(first.average, Decimal("80.00"))
        self.assertEqual(first.position_class, 1)
        self.assertEqual([sheets[e.id].position_class for e in self.world.enrollments], [1, 2, 3, 4])
        english = first.subject_results.get(subject=self.world.english)
        self.assertEqual(english.grade, "A")
        self.assertEqual(english.class_highest, Decimal("80.00"))
        self.assertEqual(english.class_lowest, Decimal("74.00"))

    def test_ties_share_a_place_and_skip_the_next(self):
        self.world.score_everything()
        tied = self.world.enrollments[1]
        Score.objects.filter(enrollment=tied).update(value=None)
        for subject in (self.world.english, self.world.maths):
            Score.objects.filter(enrollment=tied, subject=subject, component=self.world.ca).update(value=30)
            Score.objects.filter(enrollment=tied, subject=subject, component=self.world.exam).update(value=50)
        sheets = {s.enrollment_id: s for s in recompute_class(self.world.classroom, self.world.term)}
        positions = [sheets[e.id].position_class for e in self.world.enrollments]
        self.assertEqual(positions, [1, 1, 3, 4])

    def test_absent_is_excluded_when_school_says_so(self):
        self.world.score_everything()
        enrollment = self.world.enrollments[0]
        Score.objects.filter(enrollment=enrollment, subject=self.world.maths, component=self.world.exam).update(
            marker=Score.Marker.ABSENT, value=None
        )
        sheet = next(
            s for s in recompute_class(self.world.classroom, self.world.term) if s.enrollment_id == enrollment.id
        )
        self.assertFalse(sheet.incomplete)
        self.assertEqual(sheet.subject_results.get(subject=self.world.maths).components["Exam"], "AB")

    def test_missing_core_subject_blocks_position(self):
        self.world.score_everything()
        enrollment = self.world.enrollments[0]
        Score.objects.filter(enrollment=enrollment, subject=self.world.maths).delete()
        sheet = next(
            s for s in recompute_class(self.world.classroom, self.world.term) if s.enrollment_id == enrollment.id
        )
        self.assertTrue(sheet.incomplete)
        self.assertIsNone(sheet.position_class)

    def test_published_sheets_are_never_recomputed(self):
        sheets = self.world.publish()
        frozen = sheets[0]
        Score.objects.filter(enrollment=frozen.enrollment).update(value=1)
        recompute_class(self.world.classroom, self.world.term)
        frozen.refresh_from_db()
        self.assertEqual(frozen.average, Decimal("80.00"))
        self.assertEqual(frozen.state, ResultSheet.State.PUBLISHED)

    def test_third_term_promotion_uses_session_average(self):
        self.world.term.is_current = False
        self.world.term.save()
        self.world.score_everything()
        recompute_class(self.world.classroom, self.world.term)
        third = Term.objects.create(session=self.world.session, name=Term.Name.THIRD, is_current=True)
        for enrollment in self.world.enrollments:
            enrollment.pk = None
            enrollment.term = third
            enrollment.save()
        self.world.score_everything()  # enrollments now point at the third term
        self.world.school.pass_threshold = 78
        self.world.school.save()
        sheets = {s.enrollment_id: s for s in recompute_class(self.world.classroom, third)}
        ordered = [sheets[e.id] for e in self.world.enrollments]
        # Averages 80, 78, 76, 74 in both terms, so the session average matches.
        self.assertEqual([s.cumulative_average for s in ordered], [Decimal(v) for v in ("80", "78", "76", "74")])
        self.assertEqual(
            [s.promotion_status for s in ordered],
            [ResultSheet.Promotion.PROMOTED] * 2 + [ResultSheet.Promotion.REPEAT] * 2,
        )

    def test_query_count_does_not_grow_with_class_size(self):
        self.world.score_everything()
        with CaptureQueriesContext(connection) as small:
            recompute_class(self.world.classroom, self.world.term)
        big = SchoolWorld("bigclass", students=24)
        big.score_everything()
        with CaptureQueriesContext(connection) as large:
            recompute_class(big.classroom, big.term)
        # Writes still scale per sheet, but reads must not multiply per student x subject.
        per_extra_student = (len(large) - len(small)) / 20
        self.assertLess(per_extra_student, 6, f"{len(small)} -> {len(large)} queries")


class FormattingTests(TestCase):
    def test_ordinals(self):
        self.assertEqual(
            [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111)],
            ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th"],
        )
        self.assertEqual(ordinal(None), "—")

    def test_tie_label(self):
        school = School(tie_display=School.TieDisplay.POSITION_TIE)
        self.assertEqual(format_position(3, True, school), "3rd (tie)")
        self.assertEqual(format_position(3, False, school), "3rd")

    def test_pdf_text_survives_nigerian_names(self):
        self.assertEqual(latin_safe("Ọlábísí Ẹ̀mẹ́kà"), "Olábísí Emekà")
        self.assertEqual(latin_safe("₦5,000 — paid"), "N5,000 - paid")


class AnyTotalTests(TestCase):
    """Components need not add up to 100; grading and averages use the percentage."""

    def setUp(self):
        self.world = SchoolWorld("outof60", students=2)
        self.world.ca.max_score = 20
        self.world.ca.save()
        self.world.exam.max_score = 40
        self.world.exam.save()

    def test_grades_and_average_use_percentage_of_total(self):
        e0, e1 = self.world.enrollments
        for subject in (self.world.english, self.world.maths):
            for enrollment, ca, exam in ((e0, 15, 30), (e1, 10, 20)):  # 45/60 = 75%, 30/60 = 50%
                Score.objects.create(enrollment=enrollment, subject=subject, component=self.world.ca, value=ca)
                Score.objects.create(enrollment=enrollment, subject=subject, component=self.world.exam, value=exam)
        sheets = {s.enrollment_id: s for s in recompute_class(self.world.classroom, self.world.term)}
        top = sheets[e0.id]
        english = top.subject_results.get(subject=self.world.english)
        self.assertEqual(english.total, Decimal("45.00"))  # the card still shows the raw mark
        self.assertEqual(english.grade, "A")  # 75% reaches the 70-100 band
        self.assertEqual(top.average, Decimal("75.00"))
        self.assertEqual(top.total_score, Decimal("90.00"))
        self.assertEqual(sheets[e1.id].average, Decimal("50.00"))
        self.assertEqual(sheets[e1.id].subject_results.get(subject=self.world.english).grade, "C")

    def test_editing_a_maximum_keeps_entered_scores(self):
        from schools.views import save_assessment_components

        Score.objects.create(
            enrollment=self.world.enrollments[0], subject=self.world.english, component=self.world.ca, value=12
        )
        total, count = save_assessment_components(
            self.world.school, self.world.session, ["CA", "Exam", "Project"], ["30", "50", "20"]
        )
        self.assertEqual((total, count), (100, 3))
        self.assertTrue(Score.objects.filter(component=self.world.ca, value=12).exists())
        save_assessment_components(self.world.school, self.world.session, ["Exam"], ["70"])
        self.assertFalse(Score.objects.filter(value=12).exists())  # CA was removed, so its scores go

    def test_invalid_list_changes_nothing(self):
        from schools.models import AssessmentComponent
        from schools.views import save_assessment_components

        self.assertEqual(
            save_assessment_components(self.world.school, self.world.session, ["", "X"], ["5", "0"]), (0, 0)
        )
        self.assertEqual(AssessmentComponent.objects.filter(session=self.world.session).count(), 2)
