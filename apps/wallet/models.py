"""
wallet/models.py

Wallet: per-user USD balance in integer cents.
        balance_cents  — spendable immediately
        pending_cents  — vendor revenue locked for 48h post-event

WalletTransaction: append-only ledger. Never update a row, only insert.
"""
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Wallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet"
    )
    # Spendable balance (fans: ticket refunds, top-ups; vendors: after 48h unlock)
    balance_cents = models.PositiveBigIntegerField(default=0)
    # Vendor revenue locked until 48h after event kickoff
    pending_cents = models.PositiveBigIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "wallet"

    def __str__(self):
        return f"Wallet({self.user}) — ${self.balance_cents / 100:.2f} + ${self.pending_cents / 100:.2f} pending"

    @property
    def total_cents(self):
        return self.balance_cents + self.pending_cents

    @property
    def can_spend(self):
        return self.balance_cents

    def credit(self, amount_cents, description, reference_id="", tx_type="credit"):
        """Add funds to spendable balance. Creates a WalletTransaction."""
        self.balance_cents += amount_cents
        self.save(update_fields=["balance_cents", "updated_at"])
        return WalletTransaction.objects.create(
            wallet=self,
            amount_cents=amount_cents,
            tx_type=tx_type,
            description=description,
            reference_id=reference_id,
        )

    def debit(self, amount_cents, description, reference_id=""):
        """Remove from spendable balance. Returns False if insufficient."""
        if self.balance_cents < amount_cents:
            return False
        self.balance_cents -= amount_cents
        self.save(update_fields=["balance_cents", "updated_at"])
        WalletTransaction.objects.create(
            wallet=self,
            amount_cents=-amount_cents,
            tx_type=WalletTransaction.TxType.DEBIT,
            description=description,
            reference_id=reference_id,
        )
        return True

    def add_pending(self, amount_cents, description, reference_id="", available_at=None):
        """Credit vendor revenue to pending (locked) balance."""
        self.pending_cents += amount_cents
        self.save(update_fields=["pending_cents", "updated_at"])
        return WalletTransaction.objects.create(
            wallet=self,
            amount_cents=amount_cents,
            tx_type=WalletTransaction.TxType.PENDING,
            description=description,
            reference_id=reference_id,
            available_at=available_at,
        )

    def unlock_pending(self, amount_cents, description, reference_id=""):
        """
        Move amount from pending → balance.
        Called by the Celery unlock_vendor_wallet task at T+48h.
        """
        actual = min(amount_cents, self.pending_cents)
        self.pending_cents -= actual
        self.balance_cents += actual
        self.save(update_fields=["pending_cents", "balance_cents", "updated_at"])
        return WalletTransaction.objects.create(
            wallet=self,
            amount_cents=actual,
            tx_type=WalletTransaction.TxType.AVAILABLE,
            description=description,
            reference_id=reference_id,
        )


class WalletTransaction(models.Model):
    """
    Append-only ledger. One row per financial event.
    Never update — only insert.
    """

    class TxType(models.TextChoices):
        CREDIT = "credit", "Credit"                 # fan top-up, refund
        DEBIT = "debit", "Debit"                    # ticket purchase, withdrawal
        PENDING = "pending", "Pending"              # vendor revenue locked
        AVAILABLE = "available", "Available"        # pending → spendable (T+48h)
        FAILED = "failed", "Failed"                 # payment failure
        WITHDRAWAL = "withdrawal", "Withdrawal"     # cashout to M-Pesa/bank

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")

    # Positive = money in, Negative = money out
    amount_cents = models.BigIntegerField()
    tx_type = models.CharField(max_length=20, choices=TxType.choices)
    description = models.CharField(max_length=300)
    reference_id = models.CharField(max_length=200, blank=True, db_index=True)

    # For PENDING transactions — when they become spendable
    available_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "tx_type", "created_at"]),
            models.Index(fields=["reference_id"]),
        ]

    def __str__(self):
        sign = "+" if self.amount_cents >= 0 else ""
        return f"{self.tx_type} {sign}${self.amount_cents / 100:.2f} — {self.description}"
