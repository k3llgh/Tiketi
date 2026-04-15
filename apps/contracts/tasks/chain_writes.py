"""
contracts/tasks/chain_writes.py

Celery sub-tasks for every contract write operation.

These are NOT scheduled tasks — they are enqueued by:
  - Django views (on purchase confirmation)
  - Other Celery tasks (activate_relist, void_stale_payments, etc.)

Each task:
  1. Calls the appropriate caller function
  2. On success: updates the DB record with the tx hash
  3. On failure: retries with exponential backoff (max 3 attempts)
  4. On 3rd failure: marks the DB record as failed, notifies

Retry strategy:
  - attempt 1: immediate
  - attempt 2: 30 seconds later
  - attempt 3: 5 minutes later
  After 3 failures → mark failed, release seat/funds as appropriate
"""
import logging
import uuid

from celery import shared_task
from django.db import transaction

from apps.contracts.callers import (
    call_deposit,
    call_set_kickoff,
    call_set_refundable,
    call_claim_refund,
    call_refund_one,
    call_request_buyback,
    call_deposit_resale,
    call_record_return,
    call_slash,
    call_force_majeure,
)
from apps.contracts.tx import ContractCallError

logger = logging.getLogger("tiketi.contracts.tasks")

# Retry delays in seconds: 30s, then 5min
RETRY_DELAYS = [30, 300]
MAX_RETRIES  = 3


# ── submit_deposit ─────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_deposit",
    acks_late=True,
)
def submit_deposit(
    self,
    ticket_id: str,
    event_id: str,
    fan_wallet_address: str,
    amount_cents: int,
):
    """
    Submit PayoutVault.deposit() for a ticket purchase.
    Enqueued by the ticket purchase view after DB commit.
    On success: ticket.status → active.
    On 3rd failure: ticket.status → failed, seat released.
    """
    from apps.tickets.models import Ticket

    try:
        tx_hash = call_deposit(
            event_uuid=uuid.UUID(event_id),
            ticket_uuid=uuid.UUID(ticket_id),
            fan_wallet_address=fan_wallet_address,
            amount_cents=amount_cents,
        )
    except ContractCallError as exc:
        logger.warning(
            "submit_deposit failed attempt=%s ticket=%s error=%s",
            self.request.retries + 1, ticket_id, exc
        )

        # Check if we've exhausted retries
        if self.request.retries >= MAX_RETRIES - 1:
            _mark_ticket_failed(ticket_id, str(exc))
            return

        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    # Success: activate ticket
    with transaction.atomic():
        try:
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            if ticket.status == "pending_payment":
                ticket.status     = "active"
                ticket.chain_tx   = tx_hash
                ticket.save(update_fields=["status", "chain_tx"])
                logger.info("submit_deposit: ticket activated id=%s tx=%s", ticket_id, tx_hash)
            else:
                logger.warning(
                    "submit_deposit: ticket status is %s not pending_payment, skipping",
                    ticket.status
                )
        except Ticket.DoesNotExist:
            logger.error("submit_deposit: ticket not found id=%s", ticket_id)


# ── submit_set_kickoff ────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_set_kickoff",
    acks_late=True,
)
def submit_set_kickoff(
    self,
    event_id: str,
    kickoff_timestamp: int,
    vendor_wallet_address: str,
):
    """
    Register event on PayoutVault when event goes active.
    Called when event status transitions to active.
    """
    from apps.events.models import Event

    try:
        tx_hash = call_set_kickoff(
            event_uuid=uuid.UUID(event_id),
            kickoff_timestamp=kickoff_timestamp,
            vendor_wallet_address=vendor_wallet_address,
        )
    except ContractCallError as exc:
        logger.warning("submit_set_kickoff failed event=%s error=%s", event_id, exc)
        if self.request.retries >= MAX_RETRIES - 1:
            logger.error("submit_set_kickoff: all retries exhausted event=%s", event_id)
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    # Record tx hash on event
    Event.objects.filter(id=event_id).update(kickoff_tx=tx_hash)
    logger.info("submit_set_kickoff: confirmed event=%s tx=%s", event_id, tx_hash)


# ── submit_mark_returned (buyback) ────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_buyback",
    acks_late=True,
)
def submit_buyback(
    self,
    buyback_record_id: str,
    event_id: str,
    ticket_id: str,
    fan_wallet_address: str,
    ticket_type: str,
):
    """
    Submit BuybackPool.requestBuyback() — the full buyback circuit.
    Enqueued by the buyback view after DB status set to 'returned'.
    On success: BuybackRecord.refund_status → completed.
    On failure: BuybackRecord.refund_status → failed.
    """
    from apps.buyback.models import BuybackRecord

    try:
        tx_hash = call_request_buyback(
            event_uuid=uuid.UUID(event_id),
            ticket_uuid=uuid.UUID(ticket_id),
            fan_wallet_address=fan_wallet_address,
            ticket_type=ticket_type,
        )
    except ContractCallError as exc:
        logger.warning(
            "submit_buyback failed attempt=%s record=%s error=%s",
            self.request.retries + 1, buyback_record_id, exc
        )
        if self.request.retries >= MAX_RETRIES - 1:
            BuybackRecord.objects.filter(id=buyback_record_id).update(
                refund_status="failed",
                error_message=str(exc),
            )
            logger.error(
                "submit_buyback: all retries exhausted record=%s", buyback_record_id
            )
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    BuybackRecord.objects.filter(id=buyback_record_id).update(
        refund_status="completed",
        reference_id=tx_hash,
    )
    logger.info("submit_buyback: confirmed record=%s tx=%s", buyback_record_id, tx_hash)


# ── submit_set_refundable (cancellation) ──────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_set_refundable",
    acks_late=True,
)
def submit_set_refundable(self, event_id: str):
    """
    Call PayoutVault.setRefundable() on event cancellation.
    O(1) gas — fans pull their own refunds after this.
    """
    try:
        tx_hash = call_set_refundable(uuid.UUID(event_id))
    except ContractCallError as exc:
        logger.warning("submit_set_refundable failed event=%s error=%s", event_id, exc)
        if self.request.retries >= MAX_RETRIES - 1:
            logger.error("submit_set_refundable: retries exhausted event=%s", event_id)
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    logger.info("submit_set_refundable: confirmed event=%s tx=%s", event_id, tx_hash)


# ── submit_claim_refund (per-fan, cancellation) ───────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_claim_refund",
    acks_late=True,
)
def submit_claim_refund(self, event_id: str, ticket_id: str):
    """
    Submit PayoutVault.claimRefund() for one fan's ticket.
    Enqueued per-fan by send_notifications task after cancellation.
    Gas sponsored by Base Paymaster.
    """
    from apps.tickets.models import Ticket

    try:
        tx_hash = call_claim_refund(
            event_uuid=uuid.UUID(event_id),
            ticket_uuid=uuid.UUID(ticket_id),
        )
    except ContractCallError as exc:
        logger.warning(
            "submit_claim_refund failed ticket=%s error=%s", ticket_id, exc
        )
        if self.request.retries >= MAX_RETRIES - 1:
            logger.error("submit_claim_refund: retries exhausted ticket=%s", ticket_id)
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    logger.info("submit_claim_refund: confirmed ticket=%s tx=%s", ticket_id, tx_hash)


# ── submit_refund_one (postpone opt-out) ──────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_refund_one",
    acks_late=True,
)
def submit_refund_one(self, ticket_id: str):
    """
    Submit PayoutVault.refundOne() for postponement opt-out.
    Called within the 48h opt-out window after postponement.
    """
    try:
        tx_hash = call_refund_one(uuid.UUID(ticket_id))
    except ContractCallError as exc:
        logger.warning("submit_refund_one failed ticket=%s error=%s", ticket_id, exc)
        if self.request.retries >= MAX_RETRIES - 1:
            logger.error("submit_refund_one: retries exhausted ticket=%s", ticket_id)
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    logger.info("submit_refund_one: confirmed ticket=%s tx=%s", ticket_id, tx_hash)


# ── submit_resale_deposit ──────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_resale_deposit",
    acks_late=True,
)
def submit_resale_deposit(
    self,
    relist_record_id: str,
    ticket_id: str,
    amount_cents: int,
    vendor_wallet_address: str,
    new_buyer_wallet_address: str,
):
    """
    Submit BuybackPool.depositResale() after on-ramp confirms resale payment.
    40/60 split happens immediately on-chain — no T+48h lock.
    """
    from apps.buyback.models import RelistRecord

    try:
        tx_hash = call_deposit_resale(
            ticket_uuid=uuid.UUID(ticket_id),
            amount_cents=amount_cents,
            vendor_wallet_address=vendor_wallet_address,
            new_buyer_wallet_address=new_buyer_wallet_address,
        )
    except ContractCallError as exc:
        logger.warning(
            "submit_resale_deposit failed record=%s error=%s", relist_record_id, exc
        )
        if self.request.retries >= MAX_RETRIES - 1:
            RelistRecord.objects.filter(id=relist_record_id).update(status="expired")
            logger.error(
                "submit_resale_deposit: retries exhausted record=%s", relist_record_id
            )
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    RelistRecord.objects.filter(id=relist_record_id).update(
        status="sold",
        paystack_reference=tx_hash,
    )
    logger.info(
        "submit_resale_deposit: confirmed record=%s tx=%s", relist_record_id, tx_hash
    )


# ── submit_slash ───────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_slash",
    acks_late=True,
)
def submit_slash(self, vendor_wallet_address: str, reason: str, event_id: str):
    """
    Submit StakeEscrow.slash() on vendor-initiated cancellation.
    15% penalty to treasury, 85% stays locked.
    """
    from apps.events.models import Event

    try:
        tx_hash = call_slash(vendor_wallet_address, reason)
    except ContractCallError as exc:
        logger.warning(
            "submit_slash failed vendor=%s error=%s", vendor_wallet_address, exc
        )
        if self.request.retries >= MAX_RETRIES - 1:
            logger.error(
                "submit_slash: retries exhausted vendor=%s event=%s",
                vendor_wallet_address, event_id
            )
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    Event.objects.filter(id=event_id).update(
        stake_slashed=True,
        slash_tx=tx_hash,
    )
    logger.info(
        "submit_slash: confirmed vendor=%s event=%s tx=%s",
        vendor_wallet_address, event_id, tx_hash
    )


# ── submit_force_majeure ───────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_force_majeure",
    acks_late=True,
)
def submit_force_majeure(
    self,
    vendor_wallet_address: str,
    reason: str,
    event_id: str,
):
    """
    Submit StakeEscrow.forceMajeure() on admin-initiated cancellation.
    No slash — vendor not at fault.
    """
    try:
        tx_hash = call_force_majeure(vendor_wallet_address, reason)
    except ContractCallError as exc:
        logger.warning(
            "submit_force_majeure failed vendor=%s error=%s", vendor_wallet_address, exc
        )
        if self.request.retries >= MAX_RETRIES - 1:
            logger.error("submit_force_majeure: retries exhausted event=%s", event_id)
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    logger.info(
        "submit_force_majeure: confirmed vendor=%s tx=%s", vendor_wallet_address, tx_hash
    )


# ── submit_record_return ───────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="contracts.submit_record_return",
    acks_late=True,
)
def submit_record_return(self, ticket_id: str):
    """
    Emit on-chain TicketReturned proof.
    Called by activate_relist Celery task for each returned ticket.
    """
    try:
        tx_hash = call_record_return(uuid.UUID(ticket_id))
    except ContractCallError as exc:
        logger.warning("submit_record_return failed ticket=%s error=%s", ticket_id, exc)
        if self.request.retries >= MAX_RETRIES - 1:
            logger.error("submit_record_return: retries exhausted ticket=%s", ticket_id)
            return
        delay = RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    logger.info("submit_record_return: confirmed ticket=%s tx=%s", ticket_id, tx_hash)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _mark_ticket_failed(ticket_id: str, error: str):
    """
    Mark a ticket as failed after all retries exhausted.
    Releases the seat back to the FIFO pool.
    """
    from apps.tickets.models import Ticket

    with transaction.atomic():
        try:
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            if ticket.status == "pending_payment":
                ticket.status = "failed"
                ticket.save(update_fields=["status"])
                logger.error(
                    "ticket marked failed id=%s error=%s", ticket_id, error
                )
        except Ticket.DoesNotExist:
            logger.error("_mark_ticket_failed: ticket not found id=%s", ticket_id)
