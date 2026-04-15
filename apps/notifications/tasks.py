"""
notifications/tasks.py

The 4 scheduled Celery tasks for Tiketi.

Scheduled tasks:
  void_stale_payments  — every 2 minutes
  activate_relist      — triggered (not scheduled)
  expire_tickets       — daily
  send_notifications   — triggered on events

Chain write sub-tasks live in apps.contracts.tasks.chain_writes.
"""
import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("tiketi.tasks")


# ── Task 1: void_stale_payments ───────────────────────────────────────────────

@shared_task(name="tickets.void_stale_payments")
def void_stale_payments():
    """
    Run every 2 minutes via Celery beat.

    Find all tickets in pending_payment status older than 10 minutes.
    Mark them as failed and release their seats back to the FIFO pool.

    Coordinates with submit_deposit via select_for_update() to prevent
    a ticket being voided while its chain tx is confirming.
    """
    from apps.tickets.models import Ticket
    from apps.wallet.models import Wallet, WalletTransaction

    cutoff = timezone.now() - timezone.timedelta(minutes=10)

    stale = Ticket.objects.filter(
        status="pending_payment",
        purchased_at__lt=cutoff,
    ).select_related("user","event")

    voided = 0
    for ticket in stale:
        with transaction.atomic():
            try:
                # select_for_update prevents race with submit_deposit confirming
                t = Ticket.objects.select_for_update(nowait=True).get(
                    id=ticket.id, status="pending_payment"
                )
            except Ticket.DoesNotExist:
                continue  # already processed
            except Exception:
                continue  # locked by submit_deposit — skip

            t.status = "failed"
            t.save(update_fields=["status"])

            # Refund wallet deduction (purchase was debited on DB commit)
            try:
                wallet = Wallet.objects.select_for_update().get(user=t.user)
                wallet.balance_cents += t.price_paid_cents
                wallet.save(update_fields=["balance_cents","updated_at"])
                WalletTransaction.objects.create(
                    wallet=wallet,
                    amount_cents=t.price_paid_cents,
                    tx_type=WalletTransaction.TxType.CREDIT,
                    description=f"Payment void: {t.event.title} — seat released",
                )
            except Wallet.DoesNotExist:
                logger.error("void_stale: wallet not found user=%s", t.user_id)

            voided += 1
            logger.info("void_stale: voided ticket=%s user=%s", t.id, t.user_id)

        # Notify fan outside atomic block
        if voided:
            send_notifications.delay("payment_failed", str(ticket.id))

    if voided:
        logger.info("void_stale_payments: voided %s tickets", voided)

    return {"voided": voided}


# ── Task 2: activate_relist ───────────────────────────────────────────────────

@shared_task(name="tickets.activate_relist")
def activate_relist(event_id: str):
    """
    Triggered (not scheduled) when original stock hits 0.

    Called by purchase_tickets() service when the last active-stock
    ticket is sold. Simultaneously:
      1. Opens the buyback window (sets event.buyback_active=True)
      2. Flips all returned tickets to relisted at 110%
      3. Emits on-chain proof via submit_record_return for each

    The buyback window and relist activate at the same trigger — 100% sold-out.
    """
    from apps.events.models import Event
    from apps.tickets.models import Ticket
    from apps.contracts.tasks.chain_writes import submit_record_return

    with transaction.atomic():
        try:
            event = Event.objects.select_for_update().get(id=event_id)
        except Event.DoesNotExist:
            logger.error("activate_relist: event not found id=%s", event_id)
            return

        if event.status != "active":
            logger.info("activate_relist: event not active id=%s status=%s", event_id, event.status)
            return

        # Open buyback window
        event.buyback_active = True
        event.save(update_fields=["buyback_active"])

        # Find all returned tickets for this event
        returned_tickets = Ticket.objects.filter(
            event=event,
            status="returned",
        )

        # Calculate relist price (110%) for each and flip to relisted
        relisted_ids = []
        for ticket in returned_tickets:
            relist_price = int(ticket.price_paid_cents * 1.10)
            ticket.status            = "relisted"
            ticket.relist_price_cents = relist_price
            ticket.relisted_at       = timezone.now()
            ticket.save(update_fields=["status","relist_price_cents","relisted_at"])
            relisted_ids.append(str(ticket.id))

    logger.info(
        "activate_relist: event=%s relisted=%s tickets opened buyback window",
        event_id, len(relisted_ids)
    )

    # Emit on-chain proof for each returned ticket (outside atomic block)
    for ticket_id in relisted_ids:
        submit_record_return.delay(ticket_id=ticket_id)

    # Notify fans that buyback + relist are now available
    send_notifications.delay("buyback_opened", event_id)

    return {"event_id": event_id, "relisted": len(relisted_ids)}


# ── Task 3: expire_tickets ────────────────────────────────────────────────────

@shared_task(name="tickets.expire_tickets")
def expire_tickets():
    """
    Run daily via Celery beat (e.g. 04:00 EAT).

    Find all returned and relisted tickets for past events and mark expired.
    Skips failed and already-expired tickets.
    Also completes events that are past T+48h.
    """
    from apps.tickets.models import Ticket
    from apps.events.models import Event

    now = timezone.now()

    # Expire unsold returned/relisted tickets for past events
    past_event_ids = list(
        Event.objects.filter(
            kickoff__lt=now,
            status__in=["active","completed"],
        ).values_list("id", flat=True)
    )

    expired_count = Ticket.objects.filter(
        event_id__in=past_event_ids,
        status__in=["returned","relisted"],
    ).update(status="expired")

    logger.info("expire_tickets: expired %s tickets", expired_count)

    # Auto-complete events that are 48h+ past kickoff
    complete_cutoff = now - timezone.timedelta(hours=48)
    events_to_complete = Event.objects.filter(
        kickoff__lt=complete_cutoff,
        status="active",
    )

    completed = 0
    for event in events_to_complete:
        from apps.events.services import complete_event
        try:
            complete_event(event)
            completed += 1
        except Exception as exc:
            logger.error("expire_tickets: complete_event failed id=%s error=%s", event.id, exc)

    logger.info("expire_tickets: completed %s events", completed)
    return {"expired_tickets": expired_count, "completed_events": completed}


# ── Task 4: send_notifications ────────────────────────────────────────────────

@shared_task(name="notifications.send_notifications")
def send_notifications(notification_type: str, entity_id: str):
    """
    Triggered by other tasks and services. Dispatches SMS + email.
    entity_id is a ticket_id or event_id depending on notification_type.
    """
    from apps.notifications.service import send_sms, send_email

    handlers = {
        "ticket_purchased":  _notify_ticket_purchased,
        "payment_failed":    _notify_payment_failed,
        "event_cancelled":   _notify_event_cancelled,
        "event_postponed":   _notify_event_postponed,
        "buyback_opened":    _notify_buyback_opened,
        "buyback_confirmed": _notify_buyback_confirmed,
    }

    handler = handlers.get(notification_type)
    if not handler:
        logger.warning("send_notifications: unknown type=%s", notification_type)
        return

    try:
        handler(entity_id)
    except Exception as exc:
        logger.error(
            "send_notifications: handler failed type=%s id=%s error=%s",
            notification_type, entity_id, exc
        )


# ── Notification handlers ─────────────────────────────────────────────────────

def _notify_ticket_purchased(ticket_id: str):
    from apps.tickets.models import Ticket
    from apps.notifications.service import send_sms, send_email

    try:
        ticket = Ticket.objects.select_related("event","user").get(id=ticket_id)
    except Ticket.DoesNotExist:
        return

    user  = ticket.user
    event = ticket.event
    code  = ticket.current_totp if ticket.status == "active" else "Processing..."

    msg = (
        f"Tiketi: Your ticket for {event.title} on "
        f"{event.kickoff.strftime('%d %b %Y')} is confirmed. "
        f"Seat {ticket.seat_category.upper()} #{ticket.seat_number}. "
        f"Your gate code: {code}"
    )

    if user.phone:
        send_sms(str(user.phone), msg)
    if user.email:
        send_email(
            user.email,
            f"Your ticket for {event.title}",
            msg,
        )


def _notify_payment_failed(ticket_id: str):
    from apps.tickets.models import Ticket
    from apps.notifications.service import send_sms

    try:
        ticket = Ticket.objects.select_related("event","user").get(id=ticket_id)
    except Ticket.DoesNotExist:
        return

    user  = ticket.user
    event = ticket.event
    msg   = (
        f"Tiketi: Your ticket payment for {event.title} could not be processed. "
        f"Your funds have been returned. Please try again."
    )

    if user.phone:
        send_sms(str(user.phone), msg)


def _notify_event_cancelled(event_id: str):
    from apps.events.models import Event
    from apps.tickets.models import Ticket
    from apps.notifications.service import send_sms
    from apps.contracts.tasks.chain_writes import submit_claim_refund

    try:
        event = Event.objects.get(id=event_id)
    except Event.DoesNotExist:
        return

    # Get all active tickets for this event
    tickets = Ticket.objects.filter(
        event=event,
        status__in=["active","resold","pending_payment"],
    ).select_related("user")

    # Notify each fan and enqueue their refund claim
    for ticket in tickets:
        user = ticket.user
        msg  = (
            f"Tiketi: {event.title} has been cancelled. "
            f"A full refund will appear in your wallet within 24 hours."
        )
        if user.phone:
            send_sms(str(user.phone), msg)

        # Enqueue per-fan refund claim (Django-initiated, gas sponsored)
        submit_claim_refund.delay(
            event_id=str(event.id),
            ticket_id=str(ticket.id),
        )

    logger.info("notify: event_cancelled event=%s fans=%s", event_id, tickets.count())


def _notify_event_postponed(event_id: str):
    from apps.events.models import Event
    from apps.tickets.models import Ticket
    from apps.notifications.service import send_sms

    try:
        event = Event.objects.get(id=event_id)
    except Event.DoesNotExist:
        return

    tickets = Ticket.objects.filter(
        event=event, status__in=["active","resold"]
    ).select_related("user")

    deadline = event.postpone_opt_out_deadline
    deadline_str = deadline.strftime("%d %b %Y %H:%M EAT") if deadline else "48 hours"

    for ticket in tickets:
        user = ticket.user
        msg  = (
            f"Tiketi: {event.title} has been rescheduled to "
            f"{event.kickoff.strftime('%d %b %Y')}. "
            f"Your ticket remains valid. If you can\\'t attend, "
            f"request a full refund by {deadline_str} via your dashboard."
        )
        if user.phone:
            send_sms(str(user.phone), msg)


def _notify_buyback_opened(event_id: str):
    from apps.events.models import Event
    from apps.tickets.models import Ticket
    from apps.notifications.service import send_sms

    try:
        event = Event.objects.get(id=event_id)
    except Event.DoesNotExist:
        return

    tickets = Ticket.objects.filter(
        event=event, status="active"
    ).select_related("user")

    for ticket in tickets:
        user = ticket.user
        msg  = (
            f"Tiketi: {event.title} is sold out! "
            f"You can now return your ticket for a 90% refund via your dashboard."
        )
        if user.phone:
            send_sms(str(user.phone), msg)


def _notify_buyback_confirmed(ticket_id: str):
    from apps.tickets.models import Ticket
    from apps.notifications.service import send_sms

    try:
        ticket = Ticket.objects.select_related("event","user").get(id=ticket_id)
    except Ticket.DoesNotExist:
        return

    user  = ticket.user
    event = ticket.event
    msg   = (
        f"Tiketi: Your buyback for {event.title} is confirmed. "
        f"Your refund is now in your wallet."
    )
    if user.phone:
        send_sms(str(user.phone), msg)
