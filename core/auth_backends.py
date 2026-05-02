"""
Custom authentication backend allowing users to sign in with either their
username or their email address.

Why this matters: customers create accounts through two flows:
  1. The booking form (auto-creates User with username = their email)
  2. The /auth/register/ page (lets them pick any username)

Either way, they tend to type their EMAIL on the login page. Django's default
backend only accepts username, causing "credentials don't work" complaints.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        UserModel = get_user_model()
        try:
            # Try email first (case-insensitive), fall back to username
            user = UserModel.objects.filter(email__iexact=username).first()
            if user is None:
                user = UserModel.objects.filter(username__iexact=username).first()
            if user is None:
                # Run the default password hasher anyway to mitigate timing attacks
                UserModel().set_password(password)
                return None
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        except Exception:
            return None
        return None