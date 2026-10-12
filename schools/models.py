from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class School(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    class Ownership(models.TextChoices):
        PRIVATE = "private", "Private school"
        GOVERNMENT = "government", "Government (public) school"

    class PortalMode(models.TextChoices):
        ACCOUNTS = "accounts", "Account login"
        PINS = "pins", "Result PIN"
        BOTH = "both", "Accounts and PINs"

    class TieDisplay(models.TextChoices):
        POSITION = "position", "3rd"
        POSITION_TIE = "position_tie", "3rd (tie)"

    class IncompleteRule(models.TextChoices):
        BLOCK = "block", "Do not position until complete"
        OFFERED = "offered", "Position on subjects offered"

    class AverageFormula(models.TextChoices):
        SIMPLE = "simple", "Simple average of terms"
        WEIGHTED = "weighted", "Weighted terms"

    class ResultTemplate(models.TextChoices):
        CLASSIC = "classic", "Classic"
        COMPACT = "compact", "Compact"
        COLOUR = "colour", "Colour band"

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    address = models.CharField(max_length=300, blank=True)
    motto = models.CharField(max_length=200, blank=True)
    logo = models.ImageField(upload_to="schools/logos/", blank=True)
    stamp = models.ImageField(upload_to="schools/stamps/", blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    brand_colour = models.CharField(max_length=7, default="#0B3D2E")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    ownership = models.CharField(
        max_length=16,
        choices=Ownership.choices,
        default=Ownership.PRIVATE,
        help_text="Government schools charge no fees, so results are never held for owing.",
    )
    portal_mode = models.CharField(max_length=16, choices=PortalMode.choices, default=PortalMode.BOTH)
    tie_display = models.CharField(max_length=16, choices=TieDisplay.choices, default=TieDisplay.POSITION)
    incomplete_rule = models.CharField(max_length=16, choices=IncompleteRule.choices, default=IncompleteRule.BLOCK)
    exclude_absent_from_average = models.BooleanField(default=True)
    average_formula = models.CharField(max_length=16, choices=AverageFormula.choices, default=AverageFormula.SIMPLE)
    term_weights = models.JSONField(default=dict, blank=True)
    pass_threshold = models.DecimalField(max_digits=5, decimal_places=2, default=40)
    teachers_self_assign = models.BooleanField(
        default=True,
        help_text="Teachers may add the classes and subjects they teach on their My classes page.",
    )
    show_positions = models.BooleanField(
        default=True,
        help_text="Show class and subject positions on result cards, PDFs and transcripts.",
    )
    result_template = models.CharField(max_length=16, choices=ResultTemplate.choices, default=ResultTemplate.CLASSIC)
    owing_message = models.TextField(
        default="This result is withheld because of outstanding fees. Please contact the bursary."
    )
    bursary_contact = models.CharField(max_length=200, blank=True)
    setup_complete = models.BooleanField(default=False)
    setup_step = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def charges_fees(self):
        return self.ownership == self.Ownership.PRIVATE

    def current_session(self):
        return self.sessions.filter(is_current=True).first()

    def current_term(self):
        session = self.current_session()
        if not session:
            return None
        return session.terms.filter(is_current=True).first()


class AcademicSession(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="sessions")
    name = models.CharField(max_length=20)
    is_current = models.BooleanField(default=False)
    cloned_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = ("school", "name")
        ordering = ["-name"]

    def __str__(self):
        return self.name


class Term(models.Model):
    class Name(models.TextChoices):
        FIRST = "First", "First term"
        SECOND = "Second", "Second term"
        THIRD = "Third", "Third term"

    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name="terms")
    name = models.CharField(max_length=16, choices=Name.choices)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    resumption_date = models.DateField(null=True, blank=True)
    days_opened = models.PositiveSmallIntegerField(default=0)
    is_current = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)

    class Meta:
        unique_together = ("session", "name")
        ordering = ["session", "id"]

    def __str__(self):
        return f"{self.session.name} {self.name} Term"

    @property
    def school(self):
        return self.session.school


class Level(models.Model):
    class ReportType(models.TextChoices):
        SCORED = "scored", "Numeric scores"
        SKILLS = "skills", "Skill checklist"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="levels")
    name = models.CharField(max_length=40)
    order = models.PositiveSmallIntegerField(default=0)
    report_type = models.CharField(max_length=16, choices=ReportType.choices, default=ReportType.SCORED)

    class Meta:
        unique_together = ("school", "name")
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class SchoolClass(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="classes")
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="classes")
    arm = models.CharField(max_length=20)
    name = models.CharField(max_length=60)

    class Meta:
        unique_together = ("school", "level", "arm")
        ordering = ["level__order", "arm"]
        verbose_name_plural = "classes"

    def __str__(self):
        return self.name


class Subject(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=80)
    code = models.CharField(max_length=20, blank=True)

    class Meta:
        unique_together = ("school", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class LevelSubject(models.Model):
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="level_subjects")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="level_subjects")
    is_core = models.BooleanField(default=True)

    class Meta:
        unique_together = ("level", "subject")

    def __str__(self):
        return f"{self.level} · {self.subject}"


class AssessmentComponent(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="components")
    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=40)
    max_score = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(1000)])
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ("session", "name")
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.max_score})"


class GradeBand(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="grade_bands")
    level = models.ForeignKey(Level, null=True, blank=True, on_delete=models.CASCADE, related_name="grade_bands")
    min_score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2)
    label = models.CharField(max_length=10)
    remark = models.CharField(max_length=40)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-min_score"]

    def __str__(self):
        return f"{self.label} {self.min_score}-{self.max_score}"


class BehaviouralTrait(models.Model):
    class Domain(models.TextChoices):
        AFFECTIVE = "affective", "Affective"
        PSYCHOMOTOR = "psychomotor", "Psychomotor"
        SKILL = "skill", "Skill (nursery/creche)"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="traits")
    domain = models.CharField(max_length=16, choices=Domain.choices)
    name = models.CharField(max_length=60)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ("school", "domain", "name")
        ordering = ["domain", "order", "name"]

    def __str__(self):
        return self.name
