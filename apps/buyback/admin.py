"""buyback/admin.py"""
from django.contrib import admin
from apps.buyback.models import BuybackRecord, RelistRecord


@admin.register(BuybackRecord)
class BuybackRecordAdmin(admin.ModelAdmin):
    list_display  = ("id","user","event","ticket_count","refund_amount_cents","refund_status","created_at")
    list_filter   = ("refund_status","requires_admin_approval")
    readonly_fields = ("id","group_id","created_at","updated_at","reference_id")
    search_fields   = ("user__email","user__phone")
    ordering        = ("-created_at",)

    actions = ["approve_vvip_buybacks"]

    @admin.action(description="Approve selected VVIP buybacks")
    def approve_vvip_buybacks(self, request, queryset):
        from django.utils import timezone
        for record in queryset.filter(requires_admin_approval=True, refund_status="pending"):
            record.approved_by = request.user
            record.approved_at = timezone.now()
            record.save(update_fields=["approved_by","approved_at"])


@admin.register(RelistRecord)
class RelistRecordAdmin(admin.ModelAdmin):
    list_display  = ("ticket","event","relist_price_cents","status","listed_at")
    list_filter   = ("status",)
    readonly_fields = ("id","listed_at","sold_at","expired_at","platform_cut_cents","vendor_cut_cents")
    ordering        = ("-listed_at",)
