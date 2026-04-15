"""tickets/admin.py"""
from django.contrib import admin
from apps.tickets.models import Ticket, TicketEntry


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display  = ("id","event","user","seat_category","seat_number","status","ticket_type","purchased_at")
    list_filter   = ("status","ticket_type","seat_category")
    search_fields = ("id","user__email","user__phone","event__home_team","event__away_team")
    ordering      = ("-purchased_at",)
    readonly_fields = (
        "id","totp_secret","resold_totp_secret","group_id",
        "chain_tx","purchased_at","current_totp","active_totp_secret",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("event","user")


@admin.register(TicketEntry)
class TicketEntryAdmin(admin.ModelAdmin):
    list_display  = ("ticket","gate_id","recorded_at","denied","deny_reason")
    list_filter   = ("denied",)
    readonly_fields = ("recorded_at",)
    ordering      = ("-recorded_at",)
