"""gate/admin.py"""
from django.contrib import admin
from apps.gate.models import GateSyncLog


@admin.register(GateSyncLog)
class GateSyncLogAdmin(admin.ModelAdmin):
    list_display  = ("device_id","event_id","ticket_count","sync_status","synced_at")
    list_filter   = ("sync_status",)
    readonly_fields = ("id","synced_at")
    ordering      = ("-synced_at",)
