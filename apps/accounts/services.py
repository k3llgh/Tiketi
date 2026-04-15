"""
accounts/services.py

Business logic for account management.
"""
import random
import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("tiketi.accounts")


def generate_and_send_otp(user) -> str:
    from apps.accounts.models import OTPCode
    code = str(random.randint(100_000, 999_999))
    with transaction.atomic():
        OTPCode.objects.filter(user=user, used=False).update(used=True)
        OTPCode.objects.create(user=user, code=code)
    try:
        from apps.notifications.service import send_sms
        send_sms(
            phone=str(user.phone),
            message=f"Your Tiketi code is {code}. Valid 5 minutes.",
        )
    except Exception as exc:
        logger.error("OTP SMS failed user=%s error=%s", user.id, exc)
    return code


def create_fan(*, email=None, phone=None, password=None, first_name="", last_name=""):
    from apps.accounts.models import User
    if not email and not phone:
        raise ValueError("Email or phone required.")
    with transaction.atomic():
        user = User(role=User.Role.FAN, first_name=first_name, last_name=last_name)
        if email:
            user.email = email.lower().strip()
        if phone:
            user.phone = phone
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean()
        user.save()
        _create_wallet(user)
    logger.info("accounts: fan created id=%s", user.id)
    return user


def create_vendor(*, email, password, vendor_name, phone, tier):
    from apps.accounts.models import User
    with transaction.atomic():
        user = User(
            role=User.Role.VENDOR,
            email=email.lower().strip(),
            phone=phone,
            vendor_name=vendor_name,
            vendor_tier=tier,
            vendor_status=User.VendorStatus.PENDING,
        )
        user.set_password(password)
        user.full_clean()
        user.save()
        _create_wallet(user)
    logger.info("accounts: vendor created id=%s tier=%s", user.id, tier)
    return user


def activate_vendor_after_stake(user_id, tx_hash, amount_cents):
    from apps.accounts.models import User
    with transaction.atomic():
        user = User.objects.select_for_update().get(id=user_id)
        user.stake_amount_cents = amount_cents
        user.stake_paid_at = timezone.now()
        user.stake_paystack_ref = tx_hash
        if user.vendor_tier == User.VendorTier.SMALL:
            user.vendor_status = User.VendorStatus.ACTIVE
        else:
            user.vendor_status = User.VendorStatus.UNDER_REVIEW
        user.save(update_fields=[
            "stake_amount_cents", "stake_paid_at",
            "stake_paystack_ref", "vendor_status",
        ])
    return user


def request_vendor_exit(user):
    from apps.accounts.models import User
    with transaction.atomic():
        user.vendor_status = User.VendorStatus.EXITING
        user.exit_requested_at = timezone.now()
        user.save(update_fields=["vendor_status", "exit_requested_at"])
    return user.exit_unlock_date


def _create_wallet(user):
    from apps.wallet.models import Wallet
    Wallet.objects.get_or_create(user=user)
