"""
accounts/models.py

Custom AbstractBaseUser supporting both:
  - Email + password login
  - Phone + SMS OTP login

Also houses Tenant and Domain for django-tenants multi-tenancy.
"""
import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django_tenants.models import TenantMixin, DomainMixin
from phonenumber_field.modelfields import PhoneNumberField


# ── Tenant / Domain (django-tenants) ─────────────────────────────────────────

class Tenant(TenantMixin):
    """
    One row per vendor/stadium. Maps to a PostgreSQL schema.
    tiketi.co itself is the 'public' tenant (schema_name='public').
    """
    name = models.CharField(max_length=200)
    # vendor FK added below after User is defined (avoids circular import)
    created_at = models.DateTimeField(auto_now_add=True)
    auto_create_schema = True   # django-tenants creates schema on save

    class Meta:
        app_label = "accounts"

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    """Maps subdomains to tenants. kasarani.tiketi.co → Tenant(kasarani)."""

    class Meta:
        app_label = "accounts"


# ── User manager ──────────────────────────────────────────────────────────────

class UserManager(BaseUserManager):
    def _create_user(self, password, **extra_fields):
        user = self.model(**extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields["email"] = self.normalize_email(email)
        return self._create_user(password, **extra_fields)


# ── User ──────────────────────────────────────────────────────────────────────

class User(AbstractBaseUser, PermissionsMixin):
    """
    Unified user model for fans, vendors, and admins.
    Either email or phone (or both) can be the login identifier.
    """

    class Role(models.TextChoices):
        FAN = "fan", "Fan"
        VENDOR = "vendor", "Vendor"
        ADMIN = "admin", "Admin"

    class VendorTier(models.TextChoices):
        SMALL = "small", "Small (≤1,000 tickets)"
        BIG = "big", "Big (Unlimited)"

    class VendorStatus(models.TextChoices):
        PENDING = "pending", "Pending stake payment"
        UNDER_REVIEW = "under_review", "Under review (big tier)"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        EXITING = "exiting", "Exit requested (30-day timelock)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = PhoneNumberField(unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FAN)

    # ── Vendor-specific fields ─────────────────────────────────────────────────
    vendor_tier = models.CharField(
        max_length=10, choices=VendorTier.choices, null=True, blank=True
    )
    vendor_status = models.CharField(
        max_length=20, choices=VendorStatus.choices, null=True, blank=True
    )
    vendor_name = models.CharField(max_length=200, blank=True)
    stake_amount_cents = models.PositiveIntegerField(default=0)  # USD cents
    stake_paid_at = models.DateTimeField(null=True, blank=True)
    stake_paystack_ref = models.CharField(max_length=200, blank=True)
    exit_requested_at = models.DateTimeField(null=True, blank=True)
    stake_slashed_cents = models.PositiveIntegerField(default=0)

    # ── Platform fields ────────────────────────────────────────────────────────
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # ── Stats (denormalised for performance) ──────────────────────────────────
    total_purchases = models.PositiveIntegerField(default=0)
    total_buybacks = models.PositiveIntegerField(default=0)

    objects = UserManager()

    # At least one of email/phone required — enforced in clean()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        app_label = "accounts"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email or str(self.phone) or str(self.id)

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.email and not self.phone:
            raise ValidationError("At least one of email or phone is required.")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or str(self)

    @property
    def is_vendor(self):
        return self.role == self.Role.VENDOR

    @property
    def is_fan(self):
        return self.role == self.Role.FAN

    @property
    def vendor_can_sell(self):
        return self.vendor_status == self.VendorStatus.ACTIVE

    @property
    def exit_unlock_date(self):
        """Date the 30-day timelock expires and stake can be returned."""
        if self.exit_requested_at:
            from datetime import timedelta
            return self.exit_requested_at + timedelta(days=30)
        return None


# ── OTP code (phone login) ────────────────────────────────────────────────────

class OTPCode(models.Model):
    """Single-use SMS OTP for phone-based login."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otp_codes")
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    class Meta:
        app_label = "accounts"
        indexes = [models.Index(fields=["user", "used", "created_at"])]

    def is_valid(self):
        from django.conf import settings
        from datetime import timedelta
        validity = settings.TIKETI["OTP_VALIDITY_MINUTES"]
        expiry = self.created_at + timedelta(minutes=validity)
        return not self.used and timezone.now() <= expiry
