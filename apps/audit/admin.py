"""audit/admin.py"""
from django.contrib import admin
from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display  = ("event_type","user","amount_cents","chain_tx","created_at")
    list_filter   = ("event_type",)
    search_fields = ("user__email","chain_tx")
    readonly_fields = ("id","created_at")
    ordering      = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
