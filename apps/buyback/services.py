"""buyback/services.py — guard checks and buyback processing"""
import logging
from django.db import transaction
from django.conf import settings

logger = logging.getLogger("tiketi.buyback")


class BuybackError(Exception):
    pass


def check_buyback_eligible(user, event, tickets: list) -> None:
    """
    Run all guard checks. Raises BuybackError if any fail.
    Guards: event sold out (100%), < 15% returned, < 2 tx/user.
    """
    from apps.buyback.models import BuybackRecord
    from apps.tickets.models import Ticket

    cfg = settings.TIKETI

    # Guard: event must be 100% sold out to activate buyback
    if not event.buyback_eligible:
        raise BuybackError(
            "Buyback is not yet available — event must be sold out first."
        )

    # Guard: platform inventory cap
    capacity = event.total_capacity
    returned = Ticket.objects.filter(event=event, status__in=["returned","relisted"]).count()
    cap = cfg["BUYBACK_INVENTORY_CAP"]
    if capacity and (returned / capacity) >= cap:
        raise BuybackError(
            f"Buyback capacity reached ({int(cap*100)}% of tickets already returned)."
        )

    # Guard: per-user transaction limit
    user_txns = BuybackRecord.objects.filter(user=user, event=event).count()
    if user_txns >= cfg["BUYBACK_MAX_PER_USER"]:
        raise BuybackError(
            f"You have reached the maximum of {cfg['BUYBACK_MAX_PER_USER']} "
            f"buyback transactions for this event."
        )

    # Guard: VVIP requires admin approval
    for ticket in tickets:
        if ticket.seat_category == "vvip":
            raise BuybackError(
                "VVIP buybacks require admin approval. Contact support."
            )


def process_buyback(user, event, tickets: list) -> "BuybackRecord":
    """
    Process a buyback for one or all tickets in a group.
    All tickets must share the same group_id (all-or-nothing).

    Steps:
      1. Validate all guards
      2. DB: flip tickets to returned, create BuybackRecord
      3. Celery: submit_buyback() → on-chain circuit
    """
    from apps.tickets.models import Ticket
    from apps.buyback.models import BuybackRecord

    check_buyback_eligible(user, event, tickets)

    cfg      = settings.TIKETI
    is_group = len(tickets) > 1
    rate_key = "BUYBACK_GROUP_REFUND_RATE" if is_group else "BUYBACK_SINGLE_REFUND_RATE"
    rate     = cfg[rate_key]

    total_price   = sum(t.price_paid_cents for t in tickets)
    refund_amount = int(total_price * rate)
    retention     = total_price - refund_amount

    group_id = tickets[0].group_id

    with transaction.atomic():
        # Flip all tickets to returned
        Ticket.objects.filter(
            id__in=[t.id for t in tickets]
        ).update(status="returned")

        # Create one BuybackRecord for the entire transaction
        record = BuybackRecord.objects.create(
            group_id=group_id,
            event=event,
            user=user,
            ticket_count=len(tickets),
            total_original_price_cents=total_price,
            refund_amount_cents=refund_amount,
            platform_retention_cents=retention,
            refund_rate=str(rate),
            refund_status="pending",
            requires_admin_approval=False,
        )

        # Update user stats
        user.total_buybacks += 1
        user.save(update_fields=["total_buybacks"])

    # Enqueue chain write
    from apps.contracts.tasks.chain_writes import submit_buyback
    submit_buyback.delay(
        buyback_record_id=str(record.id),
        event_id=str(event.id),
        ticket_id=str(group_id),  # use group_id as the canonical ID
        fan_wallet_address=getattr(user,"smart_wallet_address","") or "",
        ticket_type="group" if is_group else "single",
    )

    logger.info(
        "buyback: processed record=%s event=%s user=%s tickets=%s refund=%s",
        record.id, event.id, user.id, len(tickets), refund_amount
    )
    return record
