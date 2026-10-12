from django.conf import settings
from django.db import models


class SubjectSheet(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"

    school_class = models.ForeignKey("schools.SchoolClass", on_delete=models.CASCADE, related_name="subject_sheets")
    subject = models.ForeignKey("schools.Subject", on_delete=models.CASCADE, related_name="sheets")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="subject_sheets")
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="submitted_sheets"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("school_class", "subject", "term")

    def __str__(self):
        return f"{self.school_class} · {self.subject} · {self.term}"


class Score(models.Model):
    class Marker(models.TextChoices):
        SCORE = "score", "Score"
        ABSENT = "absent", "Absent"
        EXEMPT = "exempt", "Exempt"

    enrollment = models.ForeignKey("records.Enrollment", on_delete=models.CASCADE, related_name="scores")
    subject = models.ForeignKey("schools.Subject", on_delete=models.CASCADE, related_name="scores")
    component = models.ForeignKey("schools.AssessmentComponent", on_delete=models.CASCADE, related_name="scores")
    value = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    marker = models.CharField(max_length=16, choices=Marker.choices, default=Marker.SCORE)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="score_edits"
    )
    updated_at = models.DateTimeField(auto_now=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("enrollment", "subject", "component")

    def __str__(self):
        return f"{self.enrollment.student} {self.subject} {self.component}"


class ResultSheet(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        REVIEWED = "reviewed", "Reviewed"
        APPROVED = "approved", "Approved"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    class Promotion(models.TextChoices):
        PENDING = "pending", "Pending"
        PROMOTED = "promoted", "Promoted"
        TRIAL = "trial", "Promoted on trial"
        REPEAT = "repeat", "Repeat"

    enrollment = models.ForeignKey("records.Enrollment", on_delete=models.CASCADE, related_name="result_sheets")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="result_sheets")
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    version = models.PositiveSmallIntegerField(default=1)
    total_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    average = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    position_class = models.PositiveSmallIntegerField(null=True, blank=True)
    position_arm = models.PositiveSmallIntegerField(null=True, blank=True)
    class_size = models.PositiveSmallIntegerField(null=True, blank=True)
    arm_size = models.PositiveSmallIntegerField(null=True, blank=True)
    subjects_offered = models.PositiveSmallIntegerField(default=0)
    grade_distribution = models.JSONField(default=dict, blank=True)
    cumulative_average = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    promotion_status = models.CharField(max_length=16, choices=Promotion.choices, default=Promotion.PENDING)
    incomplete = models.BooleanField(default=False)
    days_present = models.PositiveSmallIntegerField(null=True, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    result_code = models.CharField(max_length=24, unique=True, null=True, blank=True)
    pdf_file = models.FileField(upload_to="results/pdfs/", blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="published_results"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("enrollment", "term", "version")
        ordering = ["enrollment__student__surname"]

    def __str__(self):
        return f"{self.enrollment.student} · {self.term} v{self.version}"

    @property
    def school(self):
        return self.enrollment.student.school

    @property
    def is_immutable(self):
        return self.state in {self.State.PUBLISHED, self.State.ARCHIVED}


class SubjectResult(models.Model):
    result_sheet = models.ForeignKey(ResultSheet, on_delete=models.CASCADE, related_name="subject_results")
    subject = models.ForeignKey("schools.Subject", on_delete=models.CASCADE)
    components = models.JSONField(default=dict, blank=True)
    total = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=10, blank=True)
    remark = models.CharField(max_length=40, blank=True)
    position = models.PositiveSmallIntegerField(null=True, blank=True)
    class_highest = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    class_lowest = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    class_average = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    incomplete = models.BooleanField(default=False)

    class Meta:
        unique_together = ("result_sheet", "subject")


class BehaviouralRating(models.Model):
    enrollment = models.ForeignKey("records.Enrollment", on_delete=models.CASCADE, related_name="ratings")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="ratings")
    trait = models.ForeignKey("schools.BehaviouralTrait", on_delete=models.CASCADE, related_name="ratings")
    value = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = ("enrollment", "term", "trait")


class Comment(models.Model):
    class AuthorRole(models.TextChoices):
        CLASS_TEACHER = "class_teacher", "Class teacher"
        HEAD_OF_SCHOOL = "head_of_school", "Head of school"

    result_sheet = models.ForeignKey(ResultSheet, on_delete=models.CASCADE, related_name="comments")
    author_role = models.CharField(max_length=32, choices=AuthorRole.choices)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("result_sheet", "author_role")


class CommentBank(models.Model):
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="comment_bank")
    role = models.CharField(max_length=32, choices=Comment.AuthorRole.choices)
    min_average = models.DecimalField(max_digits=6, decimal_places=2)
    max_average = models.DecimalField(max_digits=6, decimal_places=2)
    body = models.TextField()

    class Meta:
        ordering = ["-min_average"]


class ClassCycle(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEWED = "reviewed", "Reviewed"
        APPROVED = "approved", "Approved"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    school_class = models.ForeignKey("schools.SchoolClass", on_delete=models.CASCADE, related_name="cycles")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="cycles")
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_cycles"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_cycles"
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="published_cycles"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("school_class", "term")


class Publication(models.Model):
    class Scope(models.TextChoices):
        CLASS = "class", "Class"
        ARM = "arm", "Arm"
        SCHOOL = "school", "School-wide"

    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="publications")
    term = models.ForeignKey("schools.Term", on_delete=models.CASCADE, related_name="publications")
    school_class = models.ForeignKey("schools.SchoolClass", null=True, blank=True, on_delete=models.SET_NULL)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    published_at = models.DateTimeField(auto_now_add=True)


class Amendment(models.Model):
    result_sheet = models.ForeignKey(ResultSheet, on_delete=models.CASCADE, related_name="amendments")
    previous_version = models.PositiveSmallIntegerField()
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class WorkflowEvent(models.Model):
    result_sheet = models.ForeignKey(
        ResultSheet, null=True, blank=True, on_delete=models.CASCADE, related_name="events"
    )
    class_cycle = models.ForeignKey(ClassCycle, null=True, blank=True, on_delete=models.CASCADE, related_name="events")
    from_state = models.CharField(max_length=16, blank=True)
    to_state = models.CharField(max_length=16)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
