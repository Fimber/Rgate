"""Tenant isolation, role checks and auth hardening.

Every test here guards a hole that existed before; keep them.
"""

from django.core.cache import cache
from django.test import TestCase

from accounts.models import User
from ops.models import AuditLog, ImpersonationSession
from portal.models import FeeFlag, ResultPin
from results.models import Score, SubjectSheet
from tests.factories import PASSWORD, SchoolWorld, make_user


class TwoSchools(TestCase):
    def setUp(self):
        cache.clear()
        self.a = SchoolWorld("alpha")
        self.b = SchoolWorld("bravo")


class ScoreEntryIsolationTests(TwoSchools):
    def _save(self, world_url, assignment, enrollment, component, value="35"):
        return self.client.post(
            world_url(f"app/scores/{assignment.id}/save/"),
            {"enrollment": enrollment.id, "component": component.id, "value": value},
        )

    def test_other_school_staff_cannot_write_scores(self):
        self.client.force_login(self.b.admin)
        response = self._save(self.b.url, self.a.assignment, self.a.enrollments[0], self.a.ca)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Score.objects.filter(enrollment=self.a.enrollments[0]).exists())

    def test_teacher_cannot_write_someone_elses_subject(self):
        self.client.force_login(self.a.teacher)
        response = self._save(self.a.url, self.a.maths_assignment, self.a.enrollments[0], self.a.ca)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Score.objects.exists())

    def test_assigned_teacher_can_write(self):
        self.client.force_login(self.a.teacher)
        response = self._save(self.a.url, self.a.assignment, self.a.enrollments[0], self.a.ca)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Score.objects.get().value, 35)

    def test_score_above_maximum_is_rejected(self):
        self.client.force_login(self.a.teacher)
        response = self._save(self.a.url, self.a.assignment, self.a.enrollments[0], self.a.ca, value="41")
        self.assertEqual(response.status_code, 400)

    def test_bad_marker_is_rejected(self):
        self.client.force_login(self.a.teacher)
        response = self.client.post(
            self.a.url(f"app/scores/{self.a.assignment.id}/save/"),
            {"enrollment": self.a.enrollments[0].id, "component": self.a.ca.id, "marker": "bogus"},
        )
        self.assertEqual(response.status_code, 400)

    def test_submit_and_unlock_require_post(self):
        self.client.force_login(self.a.teacher)
        response = self.client.get(self.a.url(f"app/scores/{self.a.assignment.id}/submit/"))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(SubjectSheet.objects.filter(state=SubjectSheet.State.SUBMITTED).exists())

    def test_other_school_cannot_submit_or_download(self):
        self.client.force_login(self.b.admin)
        submit = self.client.post(self.b.url(f"app/scores/{self.a.assignment.id}/submit/"))
        excel = self.client.get(self.b.url(f"app/scores/{self.a.assignment.id}/excel/"))
        self.assertEqual(submit.status_code, 404)
        self.assertEqual(excel.status_code, 404)


class ReviewPermissionTests(TwoSchools):
    def test_subject_teacher_cannot_review_class(self):
        self.client.force_login(self.a.teacher)
        response = self.client.post(self.a.url(f"app/review/{self.a.classroom.id}/"), {"action": "save_review"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("/app/progress/"))

    def test_class_teacher_review_survives_bad_numbers(self):
        self.a.score_everything()
        self.client.force_login(self.a.class_teacher)
        url = self.a.url(f"app/review/{self.a.classroom.id}/")
        self.client.get(url)
        enrollment = self.a.enrollments[0]
        response = self.client.post(url, {"action": "save_review", f"present_{enrollment.id}": "lots"})
        self.assertEqual(response.status_code, 302)


class ResultAccessTests(TwoSchools):
    def setUp(self):
        super().setUp()
        self.sheet_a = self.a.publish()[0]

    def test_staff_of_another_school_cannot_open_result(self):
        self.client.force_login(self.b.admin)
        response = self.client.get(self.b.url(f"portal/result/{self.sheet_a.id}/"))
        self.assertEqual(response.status_code, 404)
        pdf = self.client.get(self.b.url(f"portal/result/{self.sheet_a.id}/pdf/"))
        self.assertEqual(pdf.status_code, 404)

    def test_parent_of_other_child_cannot_open_result(self):
        self.client.force_login(self.b.parent)
        response = self.client.get(self.b.url(f"portal/result/{self.sheet_a.id}/"))
        self.assertEqual(response.status_code, 404)

    def test_own_parent_can_open_result(self):
        self.client.force_login(self.a.parent)
        response = self.client.get(self.a.url(f"portal/result/{self.sheet_a.id}/"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.a.student.surname)

    def test_pin_holder_without_account_can_open_result(self):
        ResultPin.objects.create(school=self.a.school, code="ABCD2345", term=self.a.term)
        response = self.client.post(
            "/portal/pin/",
            {"school": self.a.school.id, "admission_number": self.a.student.admission_number, "pin": "abcd 2345"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.a.student.surname)
        self.assertEqual(ResultPin.objects.get().uses_remaining, 4)

    def test_pin_session_does_not_unlock_other_students(self):
        ResultPin.objects.create(school=self.a.school, code="ABCD2345", term=self.a.term)
        self.client.post(
            "/portal/pin/",
            {"school": self.a.school.id, "admission_number": self.a.student.admission_number, "pin": "ABCD2345"},
        )
        other = self.a.publish()[1]
        response = self.client.get(self.a.url(f"portal/result/{other.id}/"))
        self.assertNotEqual(response.status_code, 200)

    def test_fee_block_withholds_result_from_parent(self):
        FeeFlag.objects.create(student=self.a.student, term=self.a.term, status=FeeFlag.Status.OWING)
        self.client.force_login(self.a.parent)
        response = self.client.get(self.a.url(f"portal/result/{self.sheet_a.id}/"))
        self.assertTemplateUsed(response, "portal/blocked.html")

    def test_verify_under_school_path_is_scoped_to_that_school(self):
        response = self.client.get(self.b.url(f"verify/{self.sheet_a.result_code}/"))
        self.assertContains(response, "Not found", status_code=200)
        self.assertNotContains(response, self.a.student.surname)


class FeeAndPinAdminTests(TwoSchools):
    def test_subject_teacher_cannot_change_fee_status(self):
        self.client.force_login(self.a.teacher)
        response = self.client.post(
            self.a.url("portal/fees/"), {"action": "set", "student": self.a.student.id, "status": "owing"}
        )
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(FeeFlag.objects.exists())

    def test_admin_fee_status_is_validated(self):
        self.client.force_login(self.a.admin)
        self.client.post(self.a.url("portal/fees/"), {"action": "set", "student": self.a.student.id, "status": "free"})
        self.assertFalse(FeeFlag.objects.exists())
        response = self.client.post(
            self.a.url("portal/fees/"),
            {"action": "override", "student": self.a.student.id, "hours": "forever"},
        )
        self.assertEqual(response.status_code, 302)

    def test_admin_cannot_touch_other_school_student_fees(self):
        self.client.force_login(self.a.admin)
        response = self.client.post(
            self.a.url("portal/fees/"), {"action": "set", "student": self.b.student.id, "status": "owing"}
        )
        self.assertEqual(response.status_code, 404)

    def test_pin_generation_bounds_and_garbage(self):
        self.client.force_login(self.a.admin)
        response = self.client.post(self.a.url("portal/pins/"), {"count": "ten", "uses": "9999"})
        self.assertEqual(response.status_code, 200)
        for pin in ResultPin.objects.all():
            self.assertLessEqual(pin.max_uses, 20)
            self.assertGreaterEqual(len(pin.code), 10)


class StaffCreationTests(TwoSchools):
    def test_school_admin_cannot_mint_platform_admin(self):
        self.client.force_login(self.a.admin)
        self.client.post(
            self.a.url("app/staff/"),
            {"first_name": "Evil", "last_name": "Hq", "phone": "08012345678", "role": "platform_admin"},
        )
        self.assertFalse(User.objects.filter(role=User.Role.PLATFORM_ADMIN).exists())

    def test_duplicate_phone_is_a_message_not_a_crash(self):
        self.client.force_login(self.a.admin)
        response = self.client.post(
            self.a.url("app/staff/"),
            {"first_name": "Dup", "last_name": "Licate", "phone": self.b.admin.phone, "role": "subject_teacher"},
        )
        self.assertContains(response, "already uses that phone")
        self.assertContains(response, 'value="Dup"')  # what was typed is kept

    def test_new_staff_get_a_random_temporary_password(self):
        self.client.force_login(self.a.admin)
        self.client.post(
            self.a.url("app/staff/"),
            {"first_name": "New", "last_name": "Teacher", "phone": "08012345679", "role": "class_teacher"},
        )
        user = User.objects.get(phone="08012345679")
        self.assertFalse(user.check_password("teacher1234"))
        self.assertTrue(user.must_change_password)

    def test_subject_teacher_cannot_create_students(self):
        self.client.force_login(self.a.teacher)
        self.client.post(
            self.a.url("app/students/new/"),
            {"admission_number": "X/1", "surname": "X", "first_name": "Y", "sex": "M"},
        )
        self.assertFalse(self.a.school.students.filter(admission_number="X/1").exists())


class LoginTests(TwoSchools):
    def test_login_rejects_offsite_next(self):
        response = self.client.post(
            "/login/",
            {"identifier": self.a.admin.phone, "password": PASSWORD, "next": "https://evil.example/"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example", response["Location"])

    def test_login_rate_limit_is_per_account_too(self):
        for _ in range(12):
            self.client.post("/login/", {"identifier": self.a.admin.phone, "password": "wrong"})
        response = self.client.post("/login/", {"identifier": self.a.admin.phone, "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many")

    def test_inactive_user_cannot_login(self):
        self.a.admin.is_active = False
        self.a.admin.save()
        response = self.client.post("/login/", {"identifier": self.a.admin.phone, "password": PASSWORD})
        self.assertEqual(response.status_code, 200)


class SettingsValidationTests(TwoSchools):
    def test_brand_colour_must_be_hex(self):
        self.client.force_login(self.a.admin)
        self.client.post(self.a.url("app/settings/"), {"brand_colour": "red;}body{display:none"})
        self.a.school.refresh_from_db()
        self.assertRegex(self.a.school.brand_colour, r"^#[0-9A-Fa-f]{6}$")

    def test_bad_choice_does_not_500(self):
        self.client.force_login(self.a.admin)
        response = self.client.post(self.a.url("app/settings/"), {"tie_display": "nonsense", "pass_threshold": "abc"})
        self.assertIn(response.status_code, (200, 302))
        self.a.school.refresh_from_db()
        self.assertNotEqual(self.a.school.tie_display, "nonsense")


class ImpersonationTests(TwoSchools):
    def setUp(self):
        super().setUp()
        self.hq = make_user(None, User.Role.PLATFORM_ADMIN)

    def test_impersonation_round_trip_is_logged(self):
        self.client.force_login(self.hq)
        self.client.post("/hq/impersonate/", {"target": self.a.teacher.id, "consent": "on", "reason": "Ticket 7"})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.a.teacher.id)
        self.assertTrue(AuditLog.objects.filter(action="impersonate_start").exists())
        response = self.client.post("/hq/impersonate/stop/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.hq.id)
        self.assertIsNotNone(ImpersonationSession.objects.get().ended_at)

    def test_cannot_impersonate_superuser(self):
        boss = make_user(None, User.Role.SCHOOL_ADMIN, is_superuser=True)
        self.client.force_login(self.hq)
        self.client.post("/hq/impersonate/", {"target": boss.id, "consent": "on"})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.hq.id)

    def test_school_toggle_requires_post(self):
        self.client.force_login(self.hq)
        response = self.client.get(f"/hq/schools/{self.a.school.id}/toggle/")
        self.assertEqual(response.status_code, 405)


class GovernmentSchoolTests(TestCase):
    """Government schools charge no fees: no fee screen, no holds, no owing message."""

    def setUp(self):
        cache.clear()
        from schools.models import School

        self.w = SchoolWorld("govt")
        self.w.school.ownership = School.Ownership.GOVERNMENT
        self.w.school.save()
        self.sheet = self.w.publish()[0]

    def test_owing_flag_never_holds_a_government_result(self):
        FeeFlag.objects.create(student=self.w.student, term=self.w.term, status=FeeFlag.Status.OWING)
        self.client.force_login(self.w.parent)
        response = self.client.get(self.w.url(f"portal/result/{self.sheet.id}/"))
        self.assertTemplateNotUsed(response, "portal/blocked.html")
        self.assertNotContains(response, self.w.school.owing_message)
        home = self.client.get(self.w.url("portal/"))
        self.assertNotContains(home, self.w.school.owing_message)

    def test_fee_screen_is_off_and_hidden(self):
        self.client.force_login(self.w.admin)
        response = self.client.get(self.w.url("portal/fees/"))
        self.assertEqual(response.status_code, 302)
        dashboard = self.client.get(self.w.url("app/"))
        self.assertNotContains(dashboard, "portal/fees/")

    def test_private_school_still_holds(self):
        from schools.models import School

        self.w.school.ownership = School.Ownership.PRIVATE
        self.w.school.save()
        FeeFlag.objects.create(student=self.w.student, term=self.w.term, status=FeeFlag.Status.OWING)
        self.client.force_login(self.w.parent)
        response = self.client.get(self.w.url(f"portal/result/{self.sheet.id}/"))
        self.assertTemplateUsed(response, "portal/blocked.html")

    def test_school_type_can_be_set_in_settings_and_registration(self):
        self.client.force_login(self.w.admin)
        self.client.post(self.w.url("app/settings/"), {"ownership": "private"})
        self.w.school.refresh_from_db()
        self.assertTrue(self.w.school.charges_fees)
        self.client.post(self.w.url("app/settings/"), {"ownership": "nonsense"})
        self.w.school.refresh_from_db()
        self.assertEqual(self.w.school.ownership, "private")
