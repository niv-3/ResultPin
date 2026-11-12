import re

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


def normalize_phone(value):
    number = re.sub(r"[\s()-]", "", value or "")
    if number.startswith("+234"):
        number = "0" + number[4:]
    elif number.startswith("234"):
        number = "0" + number[3:]
    return number if re.fullmatch(r"0[789][01][0-9]{8}", number) else None


class EmailOrPhoneBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = (username or "").strip()
        if not identifier or password is None:
            return None
        if "@" in identifier:
            matches = User.objects.filter(email__iexact=identifier)
        else:
            phone = normalize_phone(identifier)
            matches = User.objects.filter(phone=phone, is_staff=False, is_superuser=False) if phone else User.objects.none()
        users = list(matches[:2])
        if len(users) != 1:
            User().set_password(password)
            return None
        user = users[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
