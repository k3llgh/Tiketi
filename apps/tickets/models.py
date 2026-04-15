"""
tickets/models.py

Ticket: one row per person. Group tickets share a group_id UUID.
        Each ticket has its own TOTP secret and seat number.
TicketEntry: append-only gate scan log (no logic, pure audit).
"""
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Ticket(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RETURNED = "returned", "Returned (buyback)"
        RELISTED = "relisted", "Relisted (premium)"
        RESOLD = "resold", "Resold"
        EXPIRED = "expired", "Expired"

    class TicketType(models.TextChoices):
        SINGLE = "single", "Single"
        GROUP = "group", "Group"

    class Category(models.TextChoices):
        REGULAR = "regular", "Regular"
        VIP = "vip", "VIP"
        VVIP = "vvip", "VVIP"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        "events.Event", on_delete=models.PROTECT, related_name="tickets"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    # ── Seat ──────────────────────────────────────────────────────────────────
    seat_category = models.CharField(max_length=10, choices=Category.choices)
    seat_number = models.PositiveIntegerField()  # random within category capacity

    # ── Pricing (cents) ───────────────────────────────────────────────────────
    price_paid_cents = models.PositiveIntegerField()    # gross price fan paid
    booking_fee_cents = models.PositiveIntegerField()   # platform's cut

    # ── TOTP ──────────────────────────────────────────────────────────────────
    totp_secret = models.CharField(max_length=64)

    # ── Type & group ──────────────────────────────────────────────────────────
    ticket_type = models.CharField(
        max_length=10, choices=TicketType.choices, default=TicketType.SINGLE
    )
    # All tickets in a group share this UUID. Single tickets also have one
    # (equal to their own id) so buyback logic is uniform.
    group_id = models.UUIDField(db_index=True)
    group_size = models.PositiveSmallIntegerField(default=1)   # 1 for singles

    # ── Status ────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    # ── Relist tracking (set when this ticket is relisted) ────────────────────
    relist_price_cents = models.PositiveIntegerField(null=True, blank=True)
    relisted_at = models.DateTimeField(null=True, blank=True)
    resold_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="resold_tickets",
    )
    resold_at = models.DateTimeField(null=True, blank=True)
    resold_totp_secret = models.CharField(
        max_length=64, blank=True,
        help_text="New TOTP generated for the new buyer after resale."
    )

    # ── Postpone opt-out ──────────────────────────────────────────────────────
    # Refunded during the 48h opt-out window after event postponement.
    postpone_refunded = models.BooleanField(default=False)

    purchased_at = models.DateTimeField(auto_now_add=True)
    chain_tx = models.CharField(max_length=66, blank=True)  # PayoutVault deposit tx hash

    class Meta:
        indexes = [
            models.Index(fields=["event", "status"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["group_id"]),
            models.Index(fields=["totp_secret"]),   # gate lookup
        ]

    def __str__(self):
        return f"Ticket {self.id} — {self.event} [{self.status}]"

    @property
    def active_totp_secret(self):
        """Return the TOTP secret that should be used at the gate."""
        if self.status == self.Status.RESOLD and self.resold_totp_secret:
            return self.resold_totp_secret
        return self.totp_secret

    @property
    def current_totp(self):
        import pyotp
        return pyotp.TOTP(self.active_totp_secret).now()

    @property
    def is_group_ticket(self):
        return self.ticket_type == self.TicketType.GROUP

    @property
    def vendor_net_cents(self):
        """Amount credited to vendor for this ticket."""
        return self.price_paid_cents - self.booking_fee_cents


class TicketEntry(models.Model):
    """
    Append-only gate scan log.
    Pure audit — no re-entry logic here, unlimited scans on event day.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="entries")
    gate_id = models.CharField(max_length=50)    # identifier of the gate terminal
    recorded_at = models.DateTimeField(default=timezone.now)
    denied = models.BooleanField(default=False)
    deny_reason = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["recorded_at"]
        indexes = [models.Index(fields=["ticket", "recorded_at"])]

    def __str__(self):
        action = "DENIED" if self.denied else "ADMITTED"
        return f"{action} — Ticket {self.ticket_id} at gate {self.gate_id}"
