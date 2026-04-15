"""gate/models.py — GateSyncLog"""
import uuid
from django.db import models
from django.utils import timezone


class GateSyncLog(models.Model):
    """Server-side record of gate device sync events. Written by server on sync request."""

    class SyncStatus(models.TextChoices):
        OK      = "ok",     "Ok"
        STALE   = "stale",  "Stale"
        NO_SYNC = "no_sync","Never synced"

    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_id = models.CharField(max_length=100, db_index=True)
    event_id  = models.UUIDField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now_add=True)
    ticket_count = models.PositiveIntegerField(default=0)
    sync_status  = models.CharField(max_length=10, choices=SyncStatus.choices, default=SyncStatus.OK)

    STALE_THRESHOLD_HOURS = 2

    class Meta:
        ordering = ["-synced_at"]
        indexes  = [models.Index(fields=["device_id","-synced_at"])]

    def is_stale(self) -> bool:
        delta = timezone.now() - self.synced_at
        return delta.total_seconds() > self.STALE_THRESHOLD_HOURS * 3600

    @classmethod
    def latest_for_device(cls, device_id: str):
        return cls.objects.filter(device_id=device_id).first()
