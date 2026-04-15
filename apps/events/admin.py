"""events/admin.py"""
from django.contrib import admin
from apps.events.models import Event, SeatCategory, EventStatusLog


class SeatCategoryInline(admin.TabularInline):
    model  = SeatCategory
    extra  = 1
    readonly_fields = ("booking_fee_cents","net_price_cents","available_seats")


class EventStatusLogInline(admin.TabularInline):
    model     = EventStatusLog
    extra     = 0
    readonly_fields = ("from_status","to_status","changed_by","reason","created_at")
    can_delete = False


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display  = ("title","vendor","kickoff","status","sell_through_pct","buyback_active")
    list_filter   = ("status","buyback_active")
    search_fields = ("home_team","away_team","venue")
    ordering      = ("-kickoff",)
    readonly_fields = (
        "id","created_at","updated_at","sell_through_pct",
        "total_capacity","tickets_sold","tickets_returned",
        "kickoff_tx","slash_tx",
    )
    inlines = [SeatCategoryInline, EventStatusLogInline]

    actions = ["approve_events","pause_events","cancel_force_majeure"]

    @admin.action(description="Approve selected events (big tier)")
    def approve_events(self, request, queryset):
        from apps.events.services import approve_event
        for event in queryset.filter(status="under_review"):
            approve_event(event, request.user)
        self.message_user(request, f"Approved {queryset.count()} events.")

    @admin.action(description="Pause selected events")
    def pause_events(self, request, queryset):
        from apps.events.services import pause_event
        for event in queryset.filter(status="active"):
            pause_event(event, request.user, reason="Admin paused")

    @admin.action(description="Cancel (force majeure) — no slash")
    def cancel_force_majeure(self, request, queryset):
        from apps.events.services import cancel_event_by_admin
        for event in queryset.filter(status__in=["active","paused"]):
            cancel_event_by_admin(event, request.user, reason="Force majeure")
