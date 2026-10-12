from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra):
        if not phone:
            raise ValueError("A phone number is required")
        email = extra.pop("email", "") or ""
        if email:
            email = self.normalize_email(email)
        user = self.model(phone=self.normalize_phone(phone), email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra):
        extra.setdefault("role", User.Role.PLATFORM_ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        return self.create_user(phone, password, **extra)

    @staticmethod
    def normalize_phone(phone):
        digits = "".join(ch for ch in str(phone) if ch.isdigit())
        if digits.startswith("234") and len(digits) == 13:
            digits = "0" + digits[3:]
        return digits


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        PLATFORM_ADMIN = "platform_admin", "Platform admin"
        SCHOOL_ADMIN = "school_admin", "School admin"
        HEAD_OF_SCHOOL = "head_of_school", "Head of school"
        CLASS_TEACHER = "class_teacher", "Class teacher"
        SUBJECT_TEACHER = "subject_teacher", "Subject teacher"
        PARENT = "parent", "Parent or guardian"
        STUDENT = "student", "Student or alumnus"

    phone = models.CharField(max_length=15, unique=True)
    email = models.EmailField(blank=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    role = models.CharField(max_length=32, choices=Role.choices)
    school = models.ForeignKey(
        "schools.School",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="users",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.get_full_name()} ({self.get_role_display()})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name

    @property
    def is_platform_admin(self):
        return self.role == self.Role.PLATFORM_ADMIN or self.is_superuser

    @property
    def is_school_staff(self):
        return self.role in {
            self.Role.SCHOOL_ADMIN,
            self.Role.HEAD_OF_SCHOOL,
            self.Role.CLASS_TEACHER,
            self.Role.SUBJECT_TEACHER,
        }

    @property
    def is_school_admin_like(self):
        return self.role in {self.Role.SCHOOL_ADMIN, self.Role.HEAD_OF_SCHOOL}
