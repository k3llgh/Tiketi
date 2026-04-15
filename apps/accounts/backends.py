"""
accounts/backends.py

Two authentication backends:
  EmailBackend    — email + password (vendors, admins, fans)
  PhoneOTPBackend — phone number + SMS OTP (fans only)
"""
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class EmailBackend(ModelBackend):
    """Authenticate using email + password."""

    def authenticate(self, request, email=None, password=None, **kwargs):
        if not email or not password:
            return None
        try:
            user = User.objects.get(email__iexact=email.strip())
        except User.DoesNotExist:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class PhoneOTPBackend:
    """
    Authenticate using phone number + SMS OTP.
    OTP validity and single-use enforcement handled in the OTPCode model.
    """

    def authenticate(self, request, phone=None, otp_code=None, **kwargs):
        if not phone or not otp_code:
            return None

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            return None

        from apps.accounts.models import OTPCode
        from django.utils import timezone

        # Find the most recent unused valid OTP for this user
        otp = (
            OTPCode.objects.filter(user=user, used=False, code=str(otp_code))
            .order_by("-created_at")
            .first()
        )

        if otp and otp.is_valid():
            otp.used = True
            otp.save(update_fields=["used"])
            if not user.is_active:
                return None
            return user

        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
