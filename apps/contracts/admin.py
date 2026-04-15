"""contracts/admin.py"""
from django.contrib import admin
from apps.contracts.models import ChainTransaction


@admin.register(ChainTransaction)
class ChainTransactionAdmin(admin.ModelAdmin):
    list_display  = ("tx_type","status","tx_hash_short","block_number","gas_used","created_at")
    list_filter   = ("tx_type","status")
    readonly_fields = (
        "id","tx_hash","block_number","gas_used",
        "event_id","ticket_id","user_id","created_at","confirmed_at",
    )
    ordering = ("-created_at",)

    def tx_hash_short(self, obj):
        return obj.tx_hash[:12] + "..." if obj.tx_hash else "—"
    tx_hash_short.short_description = "Tx hash"

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
