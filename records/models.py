from django.conf import settings
from django.db import models


class Student(models.Model):
    class Sex(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        GRADUATED = "graduated", "Graduated"
        WITHDRAWN = "withdrawn", "Withdrawn"
        TRANSFERRED = "transferred", "Transferred"

    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="students")
    admission_number = models.CharField(max_length=40)
    surname = models.CharField(max_length=80)
    first_name = models.CharField(max_length=80)
    other_names = models.CharField(max_length=80, blank=True)
    sex = models.CharField(max_length=1, choices=Sex.choices)
    date_of_birth = models.DateField(null=True, blank=True)
    parent_name = models.CharField(max_length=120, blank=True)
    parent_phone = models.CharField(max_length=20, blank=True)
    parent_email = models.EmailField(blank=True)
    photo = models.ImageField(upload_to="students/photos/", blank=True)
    admission_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    parent_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    student_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="student_profile",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("school", "admission_number")
        ordering = ["surname", "first_name"]

    def __str__(self):
        return f"{self.full_name} ({self.admission_number})"

    @property
    def full_name(self):
        parts = [self.surname, self.first_name, self.other_names]
        return " ".join(p for p in parts if p)

    def current_enrollment(self, term=None):
        qs = self.enrollments.select_related("school_class", "school_class__level", "term", "session")
        if term:
            return qs.filter(term=term).first()
        return qs.order_by("-id").first()


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        LEFT = "left", "Left mid-term"

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="enrollments")
    school_class = models.ForeignKey("schools.SchoolClass", on_delete=models.CASCADE, related_name="enrollments")
    session = models.ForeignKey("schools.AcademicSession", on_delete=models.CASCADE, related_name="enrollments")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    enrolled_at = models.DateField(auto_now_add=True)
    joined_after_components = models.JSONField(default=list, blank=True)

    class Meta:
        unique_together = ("student", "term")
        ordering = ["student__surname", "student__first_name"]

    def __str__(self):
        return f"{self.student} · {self.school_class} · {self.term}"

    @property
    def school(self):
        return self.student.school


class SubjectAssignment(models.Model):
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subject_assignments")
    subject = models.ForeignKey("schools.Subject", on_delete=models.CASCADE, related_name="assignments")
    school_class = models.ForeignKey(
        "schools.SchoolClass", on_delete=models.CASCADE, related_name="subject_assignments"
    )
    session = models.ForeignKey("schools.AcademicSession", on_delete=models.CASCADE, related_name="subject_assignments")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="subject_assignments")

    class Meta:
        unique_together = ("teacher", "subject", "school_class", "term")

    def __str__(self):
        return f"{self.teacher} · {self.subject} · {self.school_class}"

    @property
    def school(self):
        return self.school_class.school


class ClassTeacherAssignment(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="class_teacher_assignments"
    )
    school_class = models.ForeignKey("schools.SchoolClass", on_delete=models.CASCADE, related_name="class_teachers")
    session = models.ForeignKey("schools.AcademicSession", on_delete=models.CASCADE, related_name="class_teachers")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="class_teachers")

    class Meta:
        unique_together = ("school_class", "term")

    def __str__(self):
        return f"{self.teacher} · {self.school_class}"
