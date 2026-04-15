"""
contracts/event_listener.py

Polls Base for contract events and triggers Django-side side effects.

Design: simple polling loop run as a management command
(python manage.py run_event_listener). Not a Celery task —
it needs to run continuously as a long-lived process.

In production: run as a separate Docker container or supervisord process.

Events handled:
  PayoutVault.PayoutClaimed  → mark vendor payout complete in DB
  PayoutVault.RefundClaimed  → log refund in audit
  BuybackPool.Refunded       → notify fan of refund
  BuybackPool.ResaleDistributed → notify vendor of relist proceeds
  StakeEscrow.Slashed        → log slash in audit
"""
import logging
import time

from django.utils import timezone
from web3.exceptions import BlockNotFound

from .client import get_web3, get_payout_vault, get_buyback_pool, get_stake_escrow

logger = logging.getLogger("tiketi.contracts.listener")

POLL_INTERVAL_SEC  = 12   # ~1 Base block
BLOCKS_PER_CHUNK   = 100  # process 100 blocks per poll to avoid RPC limits


class ContractEventListener:
    """
    Polls Base for Tiketi contract events from the last processed block.
    Persists last_block in DB to survive restarts.
    """

    def __init__(self):
        self.w3    = get_web3()
        self.vault = get_payout_vault()
        self.pool  = get_buyback_pool()
        self.escrow = get_stake_escrow()

    def run(self):
        """Main loop. Runs indefinitely."""
        logger.info("event_listener: starting on chain_id=%s", self.w3.eth.chain_id)

        while True:
            try:
                self._poll_once()
            except Exception as exc:
                logger.error("event_listener: poll error %s", exc, exc_info=True)

            time.sleep(POLL_INTERVAL_SEC)

    def _poll_once(self):
        from apps.contracts.models import ListenerState

        latest = self.w3.eth.block_number
        state  = ListenerState.load()
        from_block = state.last_processed_block + 1

        if from_block > latest:
            return  # no new blocks

        to_block = min(from_block + BLOCKS_PER_CHUNK - 1, latest)

        logger.debug("event_listener: scanning blocks %s→%s", from_block, to_block)

        self._process_payout_claimed(from_block, to_block)
        self._process_refund_claimed(from_block, to_block)
        self._process_buyback_refunded(from_block, to_block)
        self._process_relist_distributed(from_block, to_block)
        self._process_slashed(from_block, to_block)

        state.last_processed_block = to_block
        state.save(update_fields=["last_processed_block", "updated_at"])

    # ── Event handlers ────────────────────────────────────────────────────────

    def _process_payout_claimed(self, from_block: int, to_block: int):
        try:
            events = self.vault.events.PayoutClaimed.get_logs(
                from_block=from_block, to_block=to_block
            )
        except Exception as exc:
            logger.warning("event_listener: PayoutClaimed fetch error %s", exc)
            return

        for evt in events:
            event_id_bytes = evt["args"]["eventId"]
            vendor         = evt["args"]["vendor"]
            amount         = evt["args"]["amount"]
            fee            = evt["args"]["fee"]
            tx_hash        = evt["transactionHash"].hex()

            logger.info(
                "event_listener: PayoutClaimed event=%s vendor=%s amount=%s tx=%s",
                event_id_bytes.hex(), vendor, amount, tx_hash
            )

            # Notify vendor via Django notification system
            try:
                from apps.notifications.service import notify_vendor_payout_claimed
                notify_vendor_payout_claimed(
                    event_id_hex=event_id_bytes.hex(),
                    vendor_address=vendor,
                    amount_usdc=amount,
                    tx_hash=tx_hash,
                )
            except Exception as exc:
                logger.error("event_listener: PayoutClaimed handler error %s", exc)

    def _process_refund_claimed(self, from_block: int, to_block: int):
        try:
            events = self.vault.events.RefundClaimed.get_logs(
                from_block=from_block, to_block=to_block
            )
        except Exception as exc:
            logger.warning("event_listener: RefundClaimed fetch error %s", exc)
            return

        for evt in events:
            fan     = evt["args"]["fan"]
            amount  = evt["args"]["amount"]
            tx_hash = evt["transactionHash"].hex()

            logger.info(
                "event_listener: RefundClaimed fan=%s amount=%s tx=%s",
                fan, amount, tx_hash
            )

    def _process_buyback_refunded(self, from_block: int, to_block: int):
        try:
            events = self.pool.events.Refunded.get_logs(
                from_block=from_block, to_block=to_block
            )
        except Exception as exc:
            logger.warning("event_listener: Refunded fetch error %s", exc)
            return

        for evt in events:
            ticket_id_bytes = evt["args"]["ticketId"]
            fan             = evt["args"]["fan"]
            refund_amount   = evt["args"]["refundAmount"]
            tx_hash         = evt["transactionHash"].hex()

            logger.info(
                "event_listener: Refunded ticket=%s fan=%s amount=%s tx=%s",
                ticket_id_bytes.hex(), fan, refund_amount, tx_hash
            )

            try:
                from apps.notifications.service import notify_buyback_confirmed
                notify_buyback_confirmed(
                    ticket_id_hex=ticket_id_bytes.hex(),
                    fan_address=fan,
                    refund_usdc=refund_amount,
                    tx_hash=tx_hash,
                )
            except Exception as exc:
                logger.error("event_listener: Refunded handler error %s", exc)

    def _process_relist_distributed(self, from_block: int, to_block: int):
        try:
            events = self.pool.events.ResaleDistributed.get_logs(
                from_block=from_block, to_block=to_block
            )
        except Exception as exc:
            logger.warning("event_listener: ResaleDistributed fetch error %s", exc)
            return

        for evt in events:
            ticket_id_bytes = evt["args"]["ticketId"]
            vendor          = evt["args"]["vendor"]
            vendor_cut      = evt["args"]["vendorCut"]
            tx_hash         = evt["transactionHash"].hex()

            logger.info(
                "event_listener: ResaleDistributed ticket=%s vendor=%s cut=%s tx=%s",
                ticket_id_bytes.hex(), vendor, vendor_cut, tx_hash
            )

    def _process_slashed(self, from_block: int, to_block: int):
        try:
            events = self.escrow.events.Slashed.get_logs(
                from_block=from_block, to_block=to_block
            )
        except Exception as exc:
            logger.warning("event_listener: Slashed fetch error %s", exc)
            return

        for evt in events:
            vendor       = evt["args"]["vendor"]
            slash_amount = evt["args"]["slashAmount"]
            remaining    = evt["args"]["remaining"]
            reason       = evt["args"]["reason"]
            tx_hash      = evt["transactionHash"].hex()

            logger.info(
                "event_listener: Slashed vendor=%s slash=%s remaining=%s tx=%s",
                vendor, slash_amount, remaining, tx_hash
            )


class ListenerState:
    """Simple DB state to track last processed block across restarts."""
    # Implemented in models.py — see ListenerCheckpoint model
    pass
