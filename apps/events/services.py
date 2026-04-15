"""events/services.py — event lifecycle management"""
import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("tiketi.events")


def create_event(*, vendor, home_team, away_team, kickoff, venue,
                 competition="", description="", categories):
    from apps.events.models import Event, SeatCategory
    with transaction.atomic():
        event = Event.objects.create(
            vendor=vendor, home_team=home_team, away_team=away_team,
            kickoff=kickoff, venue=venue, competition=competition,
            description=description, status=Event.Status.DRAFT,
        )
        for cat in categories:
            SeatCategory.objects.create(
                event=event, category=cat["category"],
                capacity=cat["capacity"], gross_price_cents=cat["gross_price_cents"],
            )
        if vendor.vendor_tier == "big":
            event.transition(Event.Status.UNDER_REVIEW, changed_by=vendor,
                             reason="Big tier event submitted for 24h review")
            event.review_requested_at = timezone.now()
            event.review_deadline = timezone.now() + timedelta(hours=24)
            event.save(update_fields=["review_requested_at","review_deadline"])
        else:
            _activate_event(event, changed_by=vendor)
    logger.info("events: created id=%s status=%s", event.id, event.status)
    return event


def approve_event(event, admin_user):
    from apps.events.models import Event
    with transaction.atomic():
        event = Event.objects.select_for_update().get(id=event.id)
        if event.status != Event.Status.UNDER_REVIEW:
            raise ValueError(f"Cannot approve event in status {event.status}")
        event.review_approved_by = admin_user
        event.review_approved_at = timezone.now()
        event.save(update_fields=["review_approved_by","review_approved_at"])
        _activate_event(event, changed_by=admin_user)
    return event


def _activate_event(event, changed_by):
    from apps.events.models import Event
    from apps.contracts.tasks.chain_writes import submit_set_kickoff
    event.transition(Event.Status.ACTIVE, changed_by=changed_by, reason="Event activated")
    if getattr(event.vendor,"smart_wallet_address",None):
        submit_set_kickoff.delay(
            event_id=str(event.id),
            kickoff_timestamp=int(event.kickoff.timestamp()),
            vendor_wallet_address=event.vendor.smart_wallet_address,
        )


def pause_event(event, admin_user, reason=""):
    from apps.events.models import Event
    with transaction.atomic():
        event = Event.objects.select_for_update().get(id=event.id)
        event.paused_at = timezone.now()
        event.review_deadline = timezone.now() + timedelta(hours=12)
        event.save(update_fields=["paused_at","review_deadline"])
        event.transition(Event.Status.PAUSED, changed_by=admin_user, reason=reason)
    return event


def postpone_event(event, changed_by, new_kickoff, reason=""):
    from apps.events.models import Event
    with transaction.atomic():
        event = Event.objects.select_for_update().get(id=event.id)
        event.postponed_from = event.kickoff
        event.kickoff = new_kickoff
        event.postpone_opt_out_deadline = timezone.now() + timedelta(hours=48)
        event.save(update_fields=["postponed_from","kickoff","postpone_opt_out_deadline"])
        event.transition(Event.Status.POSTPONED, changed_by=changed_by, reason=reason)
    from apps.notifications.tasks import send_notifications
    send_notifications.delay("event_postponed", str(event.id))
    return event


def cancel_event_by_vendor(event, vendor, reason=""):
    from apps.events.models import Event
    with transaction.atomic():
        event = Event.objects.select_for_update().get(id=event.id)
        event.cancelled_by = Event.CancelledBy.VENDOR
        event.cancellation_reason = reason
        event.cancelled_at = timezone.now()
        event.save(update_fields=["cancelled_by","cancellation_reason","cancelled_at"])
        event.transition(Event.Status.CANCELLED, changed_by=vendor, reason=reason)
    from apps.contracts.tasks.chain_writes import submit_slash, submit_set_refundable
    if getattr(vendor,"smart_wallet_address",None):
        submit_slash.delay(vendor_wallet_address=vendor.smart_wallet_address,
                           reason=f"Vendor cancelled: {reason}", event_id=str(event.id))
    submit_set_refundable.delay(event_id=str(event.id))
    from apps.notifications.tasks import send_notifications
    send_notifications.delay("event_cancelled", str(event.id))
    return event


def cancel_event_by_admin(event, admin_user, reason=""):
    from apps.events.models import Event
    with transaction.atomic():
        event = Event.objects.select_for_update().get(id=event.id)
        event.cancelled_by = Event.CancelledBy.ADMIN
        event.cancellation_reason = reason
        event.cancelled_at = timezone.now()
        event.save(update_fields=["cancelled_by","cancellation_reason","cancelled_at"])
        event.transition(Event.Status.CANCELLED, changed_by=admin_user, reason=reason)
    from apps.contracts.tasks.chain_writes import submit_force_majeure, submit_set_refundable
    if getattr(event.vendor,"smart_wallet_address",None):
        submit_force_majeure.delay(vendor_wallet_address=event.vendor.smart_wallet_address,
                                   reason=reason, event_id=str(event.id))
    submit_set_refundable.delay(event_id=str(event.id))
    from apps.notifications.tasks import send_notifications
    send_notifications.delay("event_cancelled", str(event.id))
    return event


def complete_event(event):
    from apps.events.models import Event
    with transaction.atomic():
        event = Event.objects.select_for_update().get(id=event.id)
        if event.status != Event.Status.ACTIVE:
            return event
        event.completed_at = timezone.now()
        event.save(update_fields=["completed_at"])
        event.transition(Event.Status.COMPLETED, changed_by=None, reason="T+48h auto-complete")
    logger.info("events: completed id=%s", event.id)
    return event
