"""accounts/admin.py"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from apps.accounts.models import User, OTPCode, Tenant, Domain


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display  = ("email","phone","role","vendor_status","vendor_tier","is_active","date_joined")
    list_filter   = ("role","vendor_status","vendor_tier","is_active")
    search_fields = ("email","phone","vendor_name","first_name","last_name")
    ordering      = ("-date_joined",)
    readonly_fields = ("date_joined","stake_paid_at","exit_requested_at","total_purchases","total_buybacks")

    fieldsets = (
        (None, {"fields": ("email","phone","password")}),
        ("Personal", {"fields": ("first_name","last_name")}),
        ("Role", {"fields": ("role","is_active","is_staff","is_superuser")}),
        ("Vendor", {"fields": ("vendor_name","vendor_tier","vendor_status","stake_amount_cents","stake_paid_at","stake_paystack_ref","exit_requested_at","stake_slashed_cents")}),
        ("Web3", {"fields": ("smart_wallet_address",)}),
        ("Stats", {"fields": ("total_purchases","total_buybacks")}),
        ("Permissions", {"fields": ("groups","user_permissions")}),
    )
    add_fieldsets = (
        (None, {"fields": ("email","phone","password1","password2","role")}),
    )


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ("user","code","created_at","used")
    list_filter  = ("used",)
    readonly_fields = ("created_at",)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name","schema_name","created_at")


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain","tenant","is_primary")
