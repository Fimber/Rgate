from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("phone", "first_name", "last_name", "role", "school", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("phone", "first_name", "last_name", "email")
    ordering = ("phone",)
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Profile", {"fields": ("first_name", "last_name", "email", "role", "school")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {"fields": ("phone", "first_name", "last_name", "role", "school", "password1", "password2")}),
    )
