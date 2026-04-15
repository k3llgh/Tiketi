"""
contracts/models.py

ChainTransaction: audit log of every on-chain transaction submitted
by the platform. Links Django entities (tickets, events, buybacks)
to their on-chain representations.

This is append-only — never update a row.
"""
import uuid
from django.db import models
from django.conf import settings


class ChainTransaction(models.Model):
    """
    Immutable record of every contract write submitted by the platform.
    """

    class TxType(models.TextChoices):
        SET_KICKOFF       = "set_kickoff",       "Set event kickoff"
        DEPOSIT           = "deposit",           "Ticket deposit"
        MARK_RETURNED     = "mark_returned",     "Ticket returned (buyback)"
        BUYBACK           = "buyback",           "Buyback refund"
        SET_REFUNDABLE    = "set_refundable",    "Event cancellation — refundable"
        CLAIM_REFUND      = "claim_refund",      "Fan refund claim"
        REFUND_ONE        = "refund_one",        "Postpone opt-out refund"
        RESALE_DEPOSIT    = "resale_deposit",    "Resale 40/60 distribution"
        RECORD_RETURN     = "record_return",     "Ownership transfer proof"
        SLASH             = "slash",             "Vendor stake slash"
        FORCE_MAJEURE     = "force_majeure",     "Force majeure signal"

    class TxStatus(models.TextChoices):
        PENDING   = "pending",   "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        FAILED    = "failed",    "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tx_type    = models.CharField(max_length=30, choices=TxType.choices)
    tx_hash    = models.CharField(max_length=66, blank=True, db_index=True)
    status     = models.CharField(
        max_length=20, choices=TxStatus.choices, default=TxStatus.PENDING
    )
    error      = models.TextField(blank=True)
    retries    = models.PositiveSmallIntegerField(default=0)

    # FK references to Django entities (nullable — not all txns have all three)
    event_id   = models.UUIDField(null=True, blank=True, db_index=True)
    ticket_id  = models.UUIDField(null=True, blank=True, db_index=True)
    user_id    = models.UUIDField(null=True, blank=True, db_index=True)

    # On-chain data
    block_number  = models.PositiveBigIntegerField(null=True, blank=True)
    gas_used      = models.PositiveBigIntegerField(null=True, blank=True)
    amount_cents  = models.PositiveBigIntegerField(null=True, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tx_type", "status"]),
            models.Index(fields=["event_id", "tx_type"]),
            models.Index(fields=["ticket_id", "tx_type"]),
        ]

    def __str__(self):
        return f"{self.tx_type} [{self.status}] {self.tx_hash[:12] if self.tx_hash else 'pending'}"

    @classmethod
    def record(
        cls,
        tx_type: str,
        event_id=None,
        ticket_id=None,
        user_id=None,
        amount_cents=None,
    ) -> "ChainTransaction":
        """Create a pending ChainTransaction record before submitting to chain."""
        return cls.objects.create(
            tx_type=tx_type,
            status=cls.TxStatus.PENDING,
            event_id=event_id,
            ticket_id=ticket_id,
            user_id=user_id,
            amount_cents=amount_cents,
        )

    def confirm(self, tx_hash: str, block_number: int, gas_used: int):
        """Mark confirmed after chain receipt received."""
        from django.utils import timezone
        self.tx_hash      = tx_hash
        self.status       = self.TxStatus.CONFIRMED
        self.block_number = block_number
        self.gas_used     = gas_used
        self.confirmed_at = timezone.now()
        self.save(update_fields=[
            "tx_hash", "status", "block_number", "gas_used", "confirmed_at"
        ])

    def fail(self, error: str):
        """Mark failed after all retries exhausted."""
        self.status = self.TxStatus.FAILED
        self.error  = error
        self.save(update_fields=["status", "error"])
