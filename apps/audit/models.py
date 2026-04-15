"""audit/models.py"""
import uuid
from django.db import models
from django.conf import settings


class AuditLog(models.Model):
    class EventType(models.TextChoices):
        TICKET_PURCHASED  = "ticket_purchased"
        TICKET_RETURNED   = "ticket_returned"
        BUYBACK_PROCESSED = "buyback_processed"
        EVENT_CREATED     = "event_created"
        EVENT_CANCELLED   = "event_cancelled"
        EVENT_POSTPONED   = "event_postponed"
        VENDOR_STAKED     = "vendor_staked"
        VENDOR_SLASHED    = "vendor_slashed"
        PAYOUT_CLAIMED    = "payout_claimed"
        GATE_ADMISSION    = "gate_admission"
        GATE_DENIAL       = "gate_denial"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type  = models.CharField(max_length=50, choices=EventType.choices, db_index=True)
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    ticket_id   = models.UUIDField(null=True, blank=True, db_index=True)
    event_id    = models.UUIDField(null=True, blank=True, db_index=True)
    amount_cents = models.PositiveBigIntegerField(null=True, blank=True)
    chain_tx    = models.CharField(max_length=66, blank=True)
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    details     = models.JSONField(default=dict)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["event_type","created_at"])]

    def __str__(self):
        return f"{self.event_type} {self.created_at:%Y-%m-%d %H:%M}"
