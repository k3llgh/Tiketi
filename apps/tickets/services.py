"""
tickets/services.py — core purchase service with FIFO SKIP LOCKED
"""
import uuid
import logging
import pyotp

from django.db import transaction
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger("tiketi.tickets")


class PurchaseError(Exception):
    pass


def purchase_tickets(*, user, event, category: str, quantity: int) -> list:
    """
    Purchase tickets atomically using FIFO + SKIP LOCKED.
    Returns list of created Ticket instances.
    """
    from apps.tickets.models import Ticket
    from apps.events.models import SeatCategory

    if event.status != "active":
        raise PurchaseError(f"Event not available (status: {event.status}).")
    if quantity < 1 or quantity > 5:
        raise PurchaseError("Quantity must be 1-5.")

    ticket_type = "single" if quantity == 1 else "group"
    group_id = uuid.uuid4()

    with transaction.atomic():
        seat_cat = SeatCategory.objects.select_for_update().get(event=event, category=category)

        taken = Ticket.objects.filter(
            event=event, seat_category=category,
            status__in=["pending_payment","active","returned","relisted","resold"],
        ).count()

        available = seat_cat.capacity - taken
        if available < quantity:
            raise PurchaseError(f"Only {available} seat(s) available in {category.upper()}.")

        from apps.wallet.models import Wallet, WalletTransaction
        wallet = Wallet.objects.select_for_update().get(user=user)
        total_cost = seat_cat.gross_price_cents * quantity

        if wallet.balance_cents < total_cost:
            raise PurchaseError(
                f"Insufficient balance. Need ${total_cost/100:.2f}, "
                f"have ${wallet.balance_cents/100:.2f}."
            )

        seat_numbers = list(range(taken + 1, taken + quantity + 1))

        wallet.balance_cents -= total_cost
        wallet.save(update_fields=["balance_cents","updated_at"])

        WalletTransaction.objects.create(
            wallet=wallet,
            amount_cents=-total_cost,
            tx_type=WalletTransaction.TxType.DEBIT,
            description=(
                f"{'Group' if quantity>1 else 'Single'} ticket: "
                f"{event.home_team} vs {event.away_team} "
                f"{category.upper()} x{quantity}"
            ),
        )

        user.total_purchases += quantity
        user.save(update_fields=["total_purchases"])

        tickets = []
        for seat_num in seat_numbers:
            ticket = Ticket.objects.create(
                event=event, user=user,
                seat_category=category, seat_number=seat_num,
                price_paid_cents=seat_cat.gross_price_cents,
                booking_fee_cents=seat_cat.booking_fee_cents,
                totp_secret=pyotp.random_base32(),
                ticket_type=ticket_type,
                group_id=group_id, group_size=quantity,
                status="pending_payment",
            )
            tickets.append(ticket)

    # Enqueue chain writes after DB commit
    from apps.contracts.tasks.chain_writes import submit_deposit
    for ticket in tickets:
        submit_deposit.delay(
            ticket_id=str(ticket.id), event_id=str(event.id),
            fan_wallet_address=getattr(user,"smart_wallet_address","") or "",
            amount_cents=seat_cat.gross_price_cents,
        )

    from apps.notifications.tasks import send_notifications
    for ticket in tickets:
        send_notifications.delay("ticket_purchased", str(ticket.id))

    logger.info("tickets: purchased qty=%s cat=%s event=%s user=%s", quantity, category, event.id, user.id)
    return tickets


def process_postpone_opt_out(ticket, user) -> bool:
    """Fan opts out of postponed event — 100% refund, no guards."""
    from apps.tickets.models import Ticket

    event = ticket.event
    if event.status != "postponed":
        raise PurchaseError("Event is not postponed.")
    now = timezone.now()
    if event.postpone_opt_out_deadline and now > event.postpone_opt_out_deadline:
        raise PurchaseError("The 48h opt-out window has closed.")
    if ticket.status not in ("active","resold"):
        raise PurchaseError("Ticket not eligible for opt-out refund.")

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(id=ticket.id)
        ticket.status = "returned"
        ticket.postpone_refunded = True
        ticket.save(update_fields=["status","postpone_refunded"])

        from apps.wallet.models import Wallet, WalletTransaction
        wallet = Wallet.objects.select_for_update().get(user=user)
        wallet.balance_cents += ticket.price_paid_cents
        wallet.save(update_fields=["balance_cents","updated_at"])
        WalletTransaction.objects.create(
            wallet=wallet,
            amount_cents=ticket.price_paid_cents,
            tx_type=WalletTransaction.TxType.CREDIT,
            description=f"Postpone opt-out: {event.title}",
        )

    from apps.contracts.tasks.chain_writes import submit_refund_one
    submit_refund_one.delay(ticket_id=str(ticket.id))
    logger.info("tickets: postpone opt-out ticket=%s", ticket.id)
    return True
