"""A new school's first hour: register, run the wizard, land on a working dashboard."""

from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from results.models import ResultSheet
from schools.models import AssessmentComponent, GradeBand, Level, School, Term
from schools.slugs import RESERVED, make_school_slug, unique_school_slug

REGISTRATION = {
    "school": "Bright Future Academy",
    "state": "Lagos",
    "town": "Ikeja",
    "levels": ["primary", "junior"],
    "size": "m",
    "name": "Ngozi Okafor",
    "role": "Proprietor",
    "phone": "08031234567",
    "email": "ngozi@brightfuture.ng",
    "password": "Lagos-Sunrise-2026",
}


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_register_creates_school_with_nigerian_defaults(self):
        response = self.client.post("/register/", REGISTRATION)
        self.assertEqual(response.status_code, 302)
        school = School.objects.get(name="Bright Future Academy")
        self.assertEqual(school.slug, "brightfutureacademy")
        admin = User.objects.get(phone="08031234567")
        self.assertEqual(admin.role, User.Role.SCHOOL_ADMIN)
        self.assertEqual(admin.school, school)
        names = set(school.levels.values_list("name", flat=True))
        self.assertTrue(any(n.startswith("Primary") for n in names))
        self.assertTrue(any(n.startswith("JSS") for n in names))
        self.assertFalse(any(n.startswith(("SSS", "Nursery")) for n in names))
        session = school.current_session()
        self.assertEqual(sum(c.max_score for c in AssessmentComponent.objects.filter(session=session)), 100)
        self.assertTrue(GradeBand.objects.filter(school=school).exists())
        self.assertEqual(session.terms.count(), 3)

    def test_register_rejects_duplicates_and_bad_input(self):
        self.client.post("/register/", REGISTRATION)
        self.client.logout()
        again = self.client.post("/register/", {**REGISTRATION, "school": "Another"})
        self.assertContains(again, "already uses that phone")
        bad = self.client.post("/register/", {**REGISTRATION, "phone": "123", "email": "x@y.ng"})
        self.assertContains(bad, "Check the account details")
        self.assertEqual(School.objects.count(), 1)

    def test_register_is_rate_limited(self):
        for _ in range(6):
            self.client.post("/register/", {**REGISTRATION, "school": ""})
        response = self.client.post("/register/", REGISTRATION)
        self.assertContains(response, "Too many sign-ups")


class WizardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.post("/register/", REGISTRATION)
        self.school = School.objects.get()
        self.base = f"/{self.school.slug}/app/setup/"

    def test_unfinished_setup_redirects_to_wizard(self):
        response = self.client.get(f"/{self.school.slug}/app/scores/")
        self.assertRedirects(response, self.base, fetch_redirect_response=False)

    def test_walk_the_wizard(self):
        step1 = self.client.post(
            self.base,
            {"step": 1, "name": "Bright Future Academy", "brand_colour": "#123abc", "contact_email": "a@b.ng"},
        )
        self.assertEqual(step1.status_code, 302)
        self.client.post(
            self.base,
            {
                "step": 2,
                "session_name": "2026/2027",
                "current_term": "Second",
                "first_start": "2026-09-14",
                "first_days": "not-a-number",
                "second_end": "nonsense",
            },
        )
        self.school.refresh_from_db()
        self.assertEqual(self.school.brand_colour, "#123ABC")
        self.assertEqual(self.school.current_term().name, Term.Name.SECOND)
        first = self.school.current_session().terms.get(name=Term.Name.FIRST)
        self.assertEqual(str(first.start_date), "2026-09-14")

        self.client.post(self.base, {"step": 3, "use_defaults": "on"})
        empty = self.client.post(self.base, {"step": 4, "component_name": [""], "component_max": [""]}, follow=True)
        self.assertContains(empty, "at least one assessment component")
        self.assertTrue(AssessmentComponent.objects.filter(session=self.school.current_session()).exists())
        any_total = self.client.post(
            self.base, {"step": 4, "component_name": ["CA", "Exam"], "component_max": ["20", "40"]}, follow=True
        )
        self.assertContains(any_total, "Scores are out of 60")
        done = self.client.post(
            self.base, {"step": 5, "portal_mode": "pins", "tie_display": "position_tie", "pass_threshold": "45"}
        )
        self.assertEqual(done.status_code, 302)
        self.school.refresh_from_db()
        self.assertTrue(self.school.setup_complete)
        self.assertEqual(self.school.portal_mode, School.PortalMode.PINS)
        self.assertEqual(str(self.school.pass_threshold), "45.00")
        self.assertEqual(self.client.get(f"/{self.school.slug}/app/").status_code, 200)

    def test_wizard_step_param_is_forgiving(self):
        self.assertEqual(self.client.get(f"{self.base}?step=banana").status_code, 200)

    def test_teacher_cannot_run_setup(self):
        teacher = User.objects.create_user(
            phone="08039999999",
            password="x" * 12,
            first_name="T",
            last_name="T",
            role="subject_teacher",
            school=self.school,
        )
        self.client.force_login(teacher)
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 302)


class SlugAndTenancyTests(TestCase):
    def test_slugs_are_compact_unique_and_never_reserved(self):
        self.assertEqual(make_school_slug("St. Mary's College, Owerri"), "stmaryscollegeowerri")
        School.objects.create(name="A", slug="greenfield")
        self.assertEqual(unique_school_slug("Greenfield"), "greenfield2")
        for word in ("login", "admin", "hq", "healthz"):
            self.assertIn(word, RESERVED)
            self.assertNotIn(unique_school_slug(word), RESERVED)

    def test_hyphenated_slug_redirects_to_canonical(self):
        School.objects.create(name="Green Field", slug="greenfield")
        response = self.client.get("/green-field/login/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/greenfield/login/")

    def test_staff_on_another_schools_path_are_sent_home(self):
        School.objects.create(name="Other", slug="other", setup_complete=True)
        mine = School.objects.create(name="Mine", slug="mine", setup_complete=True)
        user = User.objects.create_user(
            phone="08030000001", password="x" * 12, first_name="A", last_name="B", role="school_admin", school=mine
        )
        self.client.force_login(user)
        response = self.client.get("/other/app/")
        self.assertEqual(response["Location"], "/mine/app/")


class SeedDemoTests(TestCase):
    def test_seed_demo_builds_a_walkable_school(self):
        call_command("seed_demo", stdout=StringIO())
        school = School.objects.get()
        self.assertTrue(school.setup_complete)
        self.assertTrue(Level.objects.filter(school=school).exists())
        self.assertTrue(ResultSheet.objects.filter(state=ResultSheet.State.PUBLISHED).exists())
        self.assertTrue(User.objects.get(phone="08055555501").check_password("parent1234"))


class GovernmentRegistrationTests(TestCase):
    def test_register_a_government_school(self):
        cache.clear()
        self.client.post("/register/", {**REGISTRATION, "ownership": "government"})
        school = School.objects.get()
        self.assertEqual(school.ownership, School.Ownership.GOVERNMENT)
        self.assertFalse(school.charges_fees)

    def test_default_is_private(self):
        cache.clear()
        self.client.post("/register/", REGISTRATION)
        self.assertTrue(School.objects.get().charges_fees)
