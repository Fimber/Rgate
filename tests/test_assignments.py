"""The principal assigns subjects to teachers by typing the subject name."""

from django.core.cache import cache
from django.test import TestCase

from records.models import SubjectAssignment
from schools.models import LevelSubject, Subject
from tests.factories import SchoolWorld


class SubjectAssignmentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = SchoolWorld("assign", students=1)
        self.other = SchoolWorld("elsewhere", students=0)
        self.url = self.w.url("app/assignments/")

    def _assign(self, user, subject_name, teacher=None, school_class=None):
        self.client.force_login(user)
        return self.client.post(
            self.url,
            {
                "action": "subject",
                "teacher": (teacher or self.w.other_teacher).id,
                "school_class": (school_class or self.w.classroom).id,
                "subject_name": subject_name,
            },
            follow=True,
        )

    def test_principal_types_a_new_subject(self):
        response = self._assign(self.w.head, "  Further   Mathematics ")
        self.assertContains(response, "now takes Further Mathematics in JSS 1 A")
        self.assertContains(response, "new subject")
        subject = Subject.objects.get(school=self.w.school, name="Further Mathematics")
        link = LevelSubject.objects.get(level=self.w.level, subject=subject)
        self.assertFalse(link.is_core)
        self.assertTrue(
            SubjectAssignment.objects.filter(teacher=self.w.other_teacher, subject=subject, term=self.w.term).exists()
        )
        # The teacher now sees it on their score-entry list.
        self.client.force_login(self.w.other_teacher)
        self.assertContains(self.client.get(self.w.url("app/scores/")), "Further Mathematics")

    def test_typed_name_reuses_existing_subject_in_any_case(self):
        before = Subject.objects.count()
        self._assign(self.w.head, "english language")
        self.assertEqual(Subject.objects.count(), before)
        self.assertTrue(SubjectAssignment.objects.filter(teacher=self.w.other_teacher, subject=self.w.english).exists())
        # It stays core, because it already was.
        self.assertTrue(LevelSubject.objects.get(level=self.w.level, subject=self.w.english).is_core)

    def test_assigning_twice_is_a_notice_not_a_duplicate(self):
        self._assign(self.w.head, "Mathematics")
        response = self._assign(self.w.head, "MATHEMATICS")
        self.assertContains(response, "already takes Mathematics")
        self.assertEqual(
            SubjectAssignment.objects.filter(teacher=self.w.other_teacher, subject=self.w.maths).count(), 1
        )

    def test_blank_subject_is_rejected(self):
        response = self._assign(self.w.head, "   ")
        self.assertContains(response, "Type the subject")

    def test_subject_teacher_cannot_assign(self):
        before = SubjectAssignment.objects.count()
        response = self._assign(self.w.teacher, "Music")
        self.assertContains(response, "Only the principal or a school admin")
        self.assertEqual(SubjectAssignment.objects.count(), before)
        self.assertFalse(Subject.objects.filter(name="Music").exists())

    def test_cannot_assign_into_another_schools_class(self):
        self.client.force_login(self.w.head)
        response = self.client.post(
            self.url,
            {
                "action": "subject",
                "teacher": self.w.teacher.id,
                "school_class": self.other.classroom.id,
                "subject_name": "Music",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_principal_can_remove_an_assignment(self):
        self.client.force_login(self.w.head)
        self.client.post(self.url, {"action": "remove_subject", "assignment": self.w.assignment.id})
        self.assertFalse(SubjectAssignment.objects.filter(pk=self.w.assignment.pk).exists())
        # Other schools' assignments are out of reach.
        response = self.client.post(self.url, {"action": "remove_subject", "assignment": self.other.assignment.id})
        self.assertEqual(response.status_code, 404)


class AddStaffWithClassesTests(TestCase):
    """The admin gives a new subject teacher their classes and subjects on the Add staff screen."""

    def setUp(self):
        cache.clear()
        self.w = SchoolWorld("staffadd", students=1)
        from schools.models import SchoolClass

        self.arm_b = SchoolClass.objects.create(school=self.w.school, level=self.w.level, arm="B", name="JSS 1 B")
        self.other = SchoolWorld("rival", students=0)
        self.url = self.w.url("app/staff/")
        self.client.force_login(self.w.admin)

    def _add(self, **extra):
        data = {"first_name": "Ada", "last_name": "Obi", "phone": "08061234567", "role": "subject_teacher"}
        data.update(extra)
        return self.client.post(self.url, data, follow=True)

    def test_subject_teacher_added_to_classes_with_typed_subjects(self):
        response = self._add(
            teach_class=[self.w.classroom.id, self.arm_b.id, self.arm_b.id],
            teach_subject=["mathematics", "Mathematics", "Further Maths"],
        )
        self.assertContains(response, "Ada Obi added to teach")
        from accounts.models import User

        ada = User.objects.get(phone="08061234567")
        taught = set(SubjectAssignment.objects.filter(teacher=ada).values_list("school_class__name", "subject__name"))
        self.assertEqual(taught, {("JSS 1 A", "Mathematics"), ("JSS 1 B", "Mathematics"), ("JSS 1 B", "Further Maths")})
        self.assertTrue(Subject.objects.filter(school=self.w.school, name="Further Maths").exists())
        # The staff table shows what they teach.
        self.assertContains(response, "Mathematics (JSS 1 B)")

    def test_class_teacher_can_be_given_their_class(self):
        from records.models import ClassTeacherAssignment

        self._add(
            role="class_teacher", form_class=self.arm_b.id, teach_class=[self.arm_b.id], teach_subject=["English"]
        )
        assignment = ClassTeacherAssignment.objects.get(school_class=self.arm_b, term=self.w.term)
        self.assertEqual(assignment.teacher.phone, "08061234567")

    def test_half_filled_row_keeps_the_form_and_creates_nothing(self):
        from accounts.models import User

        response = self._add(teach_class=[self.w.classroom.id, self.arm_b.id], teach_subject=["Mathematics", ""])
        self.assertContains(response, "Type the subject they will take in JSS 1 B")
        self.assertFalse(User.objects.filter(phone="08061234567").exists())
        self.assertContains(response, 'value="Mathematics"')

    def test_blank_rows_are_fine(self):
        from accounts.models import User

        self._add(teach_class=[""], teach_subject=[""])
        self.assertTrue(User.objects.filter(phone="08061234567").exists())

    def test_another_schools_class_is_refused(self):
        from accounts.models import User

        response = self._add(teach_class=[self.other.classroom.id], teach_subject=["Mathematics"])
        self.assertContains(response, "Choose the class")
        self.assertFalse(User.objects.filter(phone="08061234567").exists())

    def test_admin_roles_ignore_teaching_rows(self):
        from accounts.models import User

        self._add(role="school_admin", teach_class=[self.w.classroom.id], teach_subject=["Mathematics"])
        user = User.objects.get(phone="08061234567")
        self.assertFalse(SubjectAssignment.objects.filter(teacher=user).exists())


class TeacherSelfAssignTests(TestCase):
    """Teachers pick their own classes on My classes, within the school's guard rails."""

    def setUp(self):
        cache.clear()
        self.w = SchoolWorld("selfpick", students=1)
        from schools.models import SchoolClass

        self.arm_b = SchoolClass.objects.create(school=self.w.school, level=self.w.level, arm="B", name="JSS 1 B")
        self.url = self.w.url("app/my-classes/")
        self.client.force_login(self.w.teacher)

    def _add(self, rows):
        return self.client.post(
            self.url,
            {"action": "add", "teach_class": [c.id for c, _ in rows], "teach_subject": [s for _, s in rows]},
            follow=True,
        )

    def test_teacher_adds_their_own_classes(self):
        response = self._add([(self.arm_b, "english language")])
        self.assertContains(response, "Added English Language in JSS 1 B")
        self.assertTrue(
            SubjectAssignment.objects.filter(
                teacher=self.w.teacher, school_class=self.arm_b, subject=self.w.english
            ).exists()
        )
        self.assertContains(self.client.get(self.w.url("app/scores/")), "JSS 1 B")

    def test_cannot_take_a_subject_another_teacher_has(self):
        # Maths in JSS 1 A belongs to other_teacher in the fixture.
        response = self._add([(self.w.classroom, "Mathematics")])
        self.assertContains(response, "is taken by")
        self.assertFalse(SubjectAssignment.objects.filter(teacher=self.w.teacher, subject=self.w.maths).exists())

    def test_cannot_invent_subjects(self):
        response = self._add([(self.arm_b, "Mathematiks")])
        self.assertContains(response, "not one of the school")
        self.assertFalse(Subject.objects.filter(name="Mathematiks").exists())

    def test_one_bad_row_saves_nothing(self):
        self._add([(self.arm_b, "English Language"), (self.arm_b, "Nonsense")])
        self.assertFalse(SubjectAssignment.objects.filter(teacher=self.w.teacher, school_class=self.arm_b).exists())

    def test_teacher_drops_only_their_own(self):
        self.client.post(self.url, {"action": "drop", "assignment": self.w.assignment.id})
        self.assertFalse(SubjectAssignment.objects.filter(pk=self.w.assignment.pk).exists())
        response = self.client.post(self.url, {"action": "drop", "assignment": self.w.maths_assignment.id})
        self.assertEqual(response.status_code, 404)

    def test_school_can_switch_it_off(self):
        self.w.school.teachers_self_assign = False
        self.w.school.save()
        response = self._add([(self.arm_b, "English Language")])
        self.assertContains(response, "assigns classes for you")
        self.assertFalse(SubjectAssignment.objects.filter(teacher=self.w.teacher, school_class=self.arm_b).exists())

    def test_admin_toggles_the_setting(self):
        self.client.force_login(self.w.admin)
        self.client.post(self.w.url("app/settings/"), {"teachers_self_assign": ["0"]})
        self.w.school.refresh_from_db()
        self.assertFalse(self.w.school.teachers_self_assign)

    def test_class_teacher_claims_only_a_free_class(self):
        from records.models import ClassTeacherAssignment

        self.client.force_login(self.w.class_teacher)
        # JSS 1 A already has a class teacher (themselves, in the fixture); B is free.
        page = self.client.get(self.url)
        self.assertNotContains(page, "I am class teacher for")  # they already have a class
        ClassTeacherAssignment.objects.all().delete()
        from tests.factories import make_user

        rival = make_user(self.w.school, "class_teacher")
        ClassTeacherAssignment.objects.create(
            teacher=rival, school_class=self.w.classroom, session=self.w.session, term=self.w.term
        )
        response = self.client.post(self.url, {"action": "form_class", "form_class": self.w.classroom.id}, follow=True)
        self.assertContains(response, "is already class teacher")
        self.client.post(self.url, {"action": "form_class", "form_class": self.arm_b.id})
        self.assertEqual(
            ClassTeacherAssignment.objects.get(school_class=self.arm_b, term=self.w.term).teacher, self.w.class_teacher
        )

    def test_subject_teacher_cannot_claim_class_teacher(self):
        from records.models import ClassTeacherAssignment

        self.client.post(self.url, {"action": "form_class", "form_class": self.arm_b.id})
        self.assertFalse(ClassTeacherAssignment.objects.filter(school_class=self.arm_b).exists())
