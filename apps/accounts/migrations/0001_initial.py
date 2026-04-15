"""
Initial migration for the accounts app.

Creates:
  - User (custom AbstractBaseUser with email+phone dual auth)
  - OTPCode (SMS OTP for phone login)
  - Tenant (django-tenants multi-tenancy)
  - Domain (subdomain routing)
"""
import uuid
import django.db.models.deletion
import django.utils.timezone
import phonenumber_field.modelfields
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        # ── Tenant ──────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("schema_name", models.CharField(db_index=True, max_length=63, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"app_label": "accounts"},
        ),
        migrations.CreateModel(
            name="Domain",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("domain", models.CharField(db_index=True, max_length=253, unique=True)),
                ("is_primary", models.BooleanField(db_index=True, default=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="domains",
                    to="accounts.tenant",
                )),
            ],
            options={"app_label": "accounts"},
        ),

        # ── User ────────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="User",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(blank=True, max_length=254, null=True, unique=True)),
                ("phone", phonenumber_field.modelfields.PhoneNumberField(blank=True, max_length=128, null=True, region=None, unique=True)),
                ("first_name", models.CharField(blank=True, max_length=100)),
                ("last_name", models.CharField(blank=True, max_length=100)),
                ("role", models.CharField(
                    choices=[("fan", "Fan"), ("vendor", "Vendor"), ("admin", "Admin")],
                    default="fan", max_length=20,
                )),
                ("vendor_tier", models.CharField(
                    blank=True,
                    choices=[("small", "Small (≤1,000 tickets)"), ("big", "Big (Unlimited)")],
                    max_length=10, null=True,
                )),
                ("vendor_status", models.CharField(
                    blank=True,
                    choices=[
                        ("pending", "Pending stake payment"),
                        ("under_review", "Under review (big tier)"),
                        ("active", "Active"),
                        ("suspended", "Suspended"),
                        ("exiting", "Exit requested (30-day timelock)"),
                    ],
                    max_length=20, null=True,
                )),
                ("vendor_name", models.CharField(blank=True, max_length=200)),
                ("stake_amount_cents", models.PositiveIntegerField(default=0)),
                ("stake_paid_at", models.DateTimeField(blank=True, null=True)),
                ("stake_paystack_ref", models.CharField(blank=True, max_length=200)),
                ("exit_requested_at", models.DateTimeField(blank=True, null=True)),
                ("stake_slashed_cents", models.PositiveIntegerField(default=0)),
                ("smart_wallet_address", models.CharField(blank=True, max_length=42)),
                ("is_active", models.BooleanField(default=True)),
                ("is_staff", models.BooleanField(default=False)),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now)),
                ("total_purchases", models.PositiveIntegerField(default=0)),
                ("total_buybacks", models.PositiveIntegerField(default=0)),
                ("groups", models.ManyToManyField(
                    blank=True, related_name="user_set",
                    related_query_name="user", to="auth.group",
                    verbose_name="groups",
                )),
                ("user_permissions", models.ManyToManyField(
                    blank=True, related_name="user_set",
                    related_query_name="user", to="auth.permission",
                    verbose_name="user permissions",
                )),
            ],
            options={"verbose_name": "user", "verbose_name_plural": "users", "app_label": "accounts"},
        ),

        # ── OTPCode ─────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="OTPCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=6)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("used", models.BooleanField(default=False)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="otp_codes", to="accounts.user",
                )),
            ],
            options={"app_label": "accounts"},
        ),
        migrations.AddIndex(
            model_name="otpcode",
            index=models.Index(fields=["user", "used", "created_at"], name="accounts_ot_user_id_idx"),
        ),
    ]
