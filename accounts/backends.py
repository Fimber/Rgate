from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from accounts.models import User


class PhoneOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = (username or kwargs.get("phone") or kwargs.get("email") or "").strip()
        if not identifier or not password:
            return None
        lookup = Q(email__iexact=identifier)
        phone = User.objects.normalize_phone(identifier)
        if phone:
            lookup |= Q(phone=phone)
        user = User.objects.filter(lookup).filter(is_active=True).order_by("id").first()
        if user is None:
            # Spend the same time hashing so response time does not reveal which accounts exist.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
