"""
buyback/models.py

BuybackRecord: one record per buyback event (single ticket or entire group).
               Uses group_id for uniform lookup — single tickets also have a group_id
               (equal to their own ticket.id cast to UUID).

RelistRecord: tracks the secondary sale of a returned ticket.
              Created when a relisted ticket is purchased by a new buyer.
"""
import uuid
from django.db import models
from django.conf import settings


class BuybackRecord(models.Model):

    class RefundStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # group_id covers both single and group buybacks uniformly.
    # For a single-ticket buyback: group_id == ticket.id
    # For a group buyback: group_id == shared UUID on all tickets
    group_id = models.UUIDField(db_index=True)
    event = models.ForeignKey(
        "events.Event", on_delete=models.PROTECT, related_name="buyback_records"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="buyback_records",
    )

    # ── Financials (cents) ────────────────────────────────────────────────────
    ticket_count = models.PositiveSmallIntegerField(default=1)
    total_original_price_cents = models.PositiveIntegerField()
    refund_amount_cents = models.PositiveIntegerField()      # what fan receives
    platform_retention_cents = models.PositiveIntegerField() # what platform keeps
    refund_rate = models.DecimalField(max_digits=5, decimal_places=4)  # 0.9000 or 0.8000

    # ── Status ────────────────────────────────────────────────────────────────
    refund_status = models.CharField(
        max_length=20, choices=RefundStatus.choices, default=RefundStatus.PENDING
    )
    reference_id = models.CharField(max_length=200, blank=True, db_index=True)
    error_message = models.TextField(blank=True)

    # ── VVIP manual approval ──────────────────────────────────────────────────
    requires_admin_approval = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="approved_buybacks",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "event"]),
            models.Index(fields=["group_id"]),
        ]

    def __str__(self):
        return (
            f"Buyback {self.group_id} — "
            f"${self.refund_amount_cents / 100:.2f} refunded ({self.refund_status})"
        )

    @property
    def is_group_buyback(self):
        return self.ticket_count > 1


class RelistRecord(models.Model):
    """
    Created when a returned (relisted) ticket is purchased by a new buyer.
    One record per ticket (group buybacks of 3 → 3 RelistRecords).
    """

    class Status(models.TextChoices):
        LISTED = "listed", "Listed"
        SOLD = "sold", "Sold"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.OneToOneField(
        "tickets.Ticket", on_delete=models.PROTECT, related_name="relist_record"
    )
    buyback_record = models.ForeignKey(
        BuybackRecord, on_delete=models.PROTECT, related_name="relist_records"
    )
    event = models.ForeignKey(
        "events.Event", on_delete=models.PROTECT, related_name="relist_records"
    )

    # ── Pricing ───────────────────────────────────────────────────────────────
    original_price_cents = models.PositiveIntegerField()
    relist_price_cents = models.PositiveIntegerField()   # 110% of original

    # ── Sale outcome (populated when status → SOLD) ───────────────────────────
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.LISTED
    )
    new_buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="relist_purchases",
    )
    sold_at = models.DateTimeField(null=True, blank=True)
    sale_price_cents = models.PositiveIntegerField(null=True, blank=True)
    platform_cut_cents = models.PositiveIntegerField(null=True, blank=True)   # 40%
    vendor_cut_cents = models.PositiveIntegerField(null=True, blank=True)     # 60%

    # ── Paystack ref for the relist purchase ──────────────────────────────────
    paystack_reference = models.CharField(max_length=200, blank=True)

    listed_at = models.DateTimeField(auto_now_add=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-listed_at"]
        indexes = [models.Index(fields=["event", "status"])]

    def __str__(self):
        return (
            f"RelistRecord {self.ticket_id} — "
            f"${self.relist_price_cents / 100:.2f} [{self.status}]"
        )

    @property
    def platform_net_cents(self):
        """
        Platform net on this relist:
        Received 40% of sale, but previously paid out the buyback refund.
        Tracked at the BuybackRecord level for the full picture.
        """
        return self.platform_cut_cents or 0
