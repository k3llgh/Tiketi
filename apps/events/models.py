"""
events/models.py

Event: 7-state machine (draft → under_review → active → paused →
       postponed / cancelled / completed).
SeatCategory: per-event pricing for Regular / VIP / VVIP.
EventStatusLog: immutable audit trail of every status transition.
"""
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Event(models.Model):

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        UNDER_REVIEW = "under_review", "Under review"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        POSTPONED = "postponed", "Postponed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    class CancelledBy(models.TextChoices):
        VENDOR = "vendor", "Vendor"
        ADMIN = "admin", "Admin (force majeure)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="events",
        limit_choices_to={"role": "vendor"},
    )

    # ── Event details ──────────────────────────────────────────────────────────
    home_team = models.CharField(max_length=150)
    away_team = models.CharField(max_length=150)
    competition = models.CharField(max_length=100, blank=True)
    venue = models.CharField(max_length=200)
    kickoff = models.DateTimeField()
    description = models.TextField(blank=True)
    poster = models.ImageField(upload_to="event_posters/", null=True, blank=True)

    # ── Status machine ────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )

    # ── Cancellation ──────────────────────────────────────────────────────────
    cancelled_by = models.CharField(
        max_length=10, choices=CancelledBy.choices, null=True, blank=True
    )
    cancellation_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    stake_slashed = models.BooleanField(default=False)   # True after vendor-cancel slash

    # ── Postponement ──────────────────────────────────────────────────────────
    postponed_from = models.DateTimeField(null=True, blank=True)  # original kickoff
    postpone_opt_out_deadline = models.DateTimeField(null=True, blank=True)

    # ── Admin pause / review ──────────────────────────────────────────────────
    paused_at = models.DateTimeField(null=True, blank=True)
    review_deadline = models.DateTimeField(null=True, blank=True)  # paused + 12h

    # ── Big-tier review ───────────────────────────────────────────────────────
    review_requested_at = models.DateTimeField(null=True, blank=True)
    review_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="reviewed_events",
    )
    review_approved_at = models.DateTimeField(null=True, blank=True)

    # ── Completion ────────────────────────────────────────────────────────────
    completed_at = models.DateTimeField(null=True, blank=True)
    kickoff_tx   = models.CharField(max_length=66, blank=True)  # setKickoff() tx hash
    slash_tx     = models.CharField(max_length=66, blank=True)  # slash() tx hash

    # Buyback window — set True by activate_relist Celery task when stock hits 0
    buyback_active = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-kickoff"]
        indexes = [
            models.Index(fields=["status", "kickoff"]),
            models.Index(fields=["vendor", "status"]),
        ]

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} — {self.kickoff:%d %b %Y}"

    @property
    def title(self):
        return f"{self.home_team} vs {self.away_team}"

    @property
    def total_capacity(self):
        return self.seat_categories.aggregate(
            total=models.Sum("capacity")
        )["total"] or 0

    @property
    def tickets_sold(self):
        return self.tickets.filter(status="active").count()

    @property
    def sell_through_rate(self):
        if self.total_capacity == 0:
            return 0.0
        return self.tickets_sold / self.total_capacity

    @property
    def tickets_returned(self):
        return self.tickets.filter(status="returned").count()

    @property
    def original_stock_sold_out(self):
        """True when every originally issued active ticket is gone."""
        return self.tickets.filter(
            status__in=["active"]
        ).count() == 0 and self.tickets_sold > 0

    @property
    def buyback_eligible(self):
        cfg = settings.TIKETI
        returned = self.tickets_returned
        capacity = self.total_capacity
        if capacity == 0:
            return False
        return (
            self.sell_through_rate >= cfg["BUYBACK_SELL_THROUGH_THRESHOLD"]
            and (returned / capacity) < cfg["BUYBACK_INVENTORY_CAP"]
        )

    @property
    def is_on_event_day(self):
        return self.kickoff.date() == timezone.now().date()

    def transition(self, new_status, changed_by, reason=""):
        """
        Central state-transition method. Logs every change.
        Callers must validate the transition is legal before calling.
        """
        old_status = self.status
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])
        EventStatusLog.objects.create(
            event=self,
            from_status=old_status,
            to_status=new_status,
            changed_by=changed_by,
            reason=reason,
        )


class SeatCategory(models.Model):

    class Category(models.TextChoices):
        REGULAR = "regular", "Regular"
        VIP = "vip", "VIP"
        VVIP = "vvip", "VVIP"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="seat_categories"
    )
    category = models.CharField(max_length=10, choices=Category.choices)
    capacity = models.PositiveIntegerField()

    # Pricing — all in USD cents (integer, no floats)
    gross_price_cents = models.PositiveIntegerField(
        help_text="Price shown to fan. Booking fee absorbed inside this."
    )

    @property
    def booking_fee_cents(self):
        cfg = settings.TIKETI
        fee = int(self.gross_price_cents * cfg["BOOKING_FEE_RATE"])
        return max(fee, cfg["BOOKING_FEE_FLOOR_CENTS"])

    @property
    def net_price_cents(self):
        """Amount vendor earns per ticket after platform booking fee."""
        return self.gross_price_cents - self.booking_fee_cents

    @property
    def available_seats(self):
        sold = self.event.tickets.filter(
            seat_category=self.category,
            status__in=["active", "returned", "relisted", "resold"]
        ).count()
        return max(0, self.capacity - sold)

    @property
    def is_sold_out(self):
        return self.available_seats == 0

    class Meta:
        unique_together = [("event", "category")]

    def __str__(self):
        return f"{self.event} — {self.get_category_display()} (${self.gross_price_cents / 100:.2f})"


class EventStatusLog(models.Model):
    """Immutable log of every event status transition."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="status_logs")
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.event} | {self.from_status} → {self.to_status}"
