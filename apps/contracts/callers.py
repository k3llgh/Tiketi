"""
contracts/callers.py

High-level typed functions for every contract write Tiketi makes.
Each function:
  - Takes Django model IDs (UUIDs, strings)
  - Encodes them into the correct on-chain types
  - Calls submit_tx() and returns the tx hash string
  - Logs the operation for audit trail

These are called by Celery tasks (never directly from views).
All functions are synchronous — Celery handles async execution.
"""
import logging
import uuid

from .client import get_stake_escrow, get_payout_vault, get_buyback_pool
from .encoder import (
    uuid_to_bytes32,
    usd_cents_to_usdc_units,
    to_checksum_address,
    get_ticket_type_enum,
    get_tier_enum,
)
from .tx import submit_tx, call_view

logger = logging.getLogger("tiketi.contracts.callers")


# ── StakeEscrow callers ───────────────────────────────────────────────────────

def call_slash(vendor_wallet_address: str, reason: str) -> str:
    """
    Slash 15% of vendor stake to treasury.
    Called when vendor cancels an event.

    Returns: tx hash string
    """
    escrow  = get_stake_escrow()
    address = to_checksum_address(vendor_wallet_address)

    logger.info("contracts: slashing vendor=%s reason=%r", address, reason)

    receipt = submit_tx(
        escrow.functions.slash(address, reason)
    )
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: slash confirmed tx=%s", tx_hash)
    return tx_hash


def call_force_majeure(vendor_wallet_address: str, reason: str) -> str:
    """
    Mark vendor event as force majeure — no slash applied.
    Called on admin-initiated cancellation (flood, government ban, etc.).

    Returns: tx hash string
    """
    escrow  = get_stake_escrow()
    address = to_checksum_address(vendor_wallet_address)

    logger.info("contracts: force_majeure vendor=%s reason=%r", address, reason)

    receipt = submit_tx(
        escrow.functions.forceMajeure(address, reason)
    )
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: force_majeure confirmed tx=%s", tx_hash)
    return tx_hash


def query_vendor_state(vendor_wallet_address: str) -> dict:
    """
    Read vendor state from StakeEscrow (no gas).
    Returns dict with tier, status, stakedAmount, claimableAmount, etc.
    """
    escrow  = get_stake_escrow()
    address = to_checksum_address(vendor_wallet_address)
    result  = call_view(escrow.functions.getVendor(address))

    return {
        "tier":             result[0],
        "status":           result[1],
        "staked_amount":    result[2],
        "claimable_amount": result[3],
        "slashed_amount":   result[4],
        "exit_requested_at": result[5],
    }


def query_vendor_active(vendor_wallet_address: str) -> bool:
    """Check if a vendor is currently active on-chain."""
    escrow  = get_stake_escrow()
    address = to_checksum_address(vendor_wallet_address)
    return call_view(escrow.functions.isActive(address))


# ── PayoutVault callers ───────────────────────────────────────────────────────

def call_set_kickoff(
    event_uuid: uuid.UUID,
    kickoff_timestamp: int,
    vendor_wallet_address: str,
) -> str:
    """
    Register event kickoff timestamp and vendor address on-chain.
    Called by Django when an event transitions to active status.
    Immutable once set.

    Args:
        event_uuid:          Django event UUID
        kickoff_timestamp:   Unix timestamp of event kickoff
        vendor_wallet_address: Vendor's ERC-4337 smart wallet address

    Returns: tx hash string
    """
    vault     = get_payout_vault()
    event_id  = uuid_to_bytes32(event_uuid)
    vendor    = to_checksum_address(vendor_wallet_address)

    logger.info(
        "contracts: set_kickoff event=%s ts=%s vendor=%s",
        event_uuid, kickoff_timestamp, vendor
    )

    receipt = submit_tx(
        vault.functions.setKickoff(event_id, kickoff_timestamp, vendor)
    )
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: set_kickoff confirmed tx=%s", tx_hash)
    return tx_hash


def call_deposit(
    event_uuid: uuid.UUID,
    ticket_uuid: uuid.UUID,
    fan_wallet_address: str,
    amount_cents: int,
) -> str:
    """
    Deposit fan's USDC payment into PayoutVault for a ticket purchase.
    Called by the submit_deposit Celery sub-task after DB commit.
    Idempotent — safe to retry on chain timeout.

    Args:
        event_uuid:        Django event UUID
        ticket_uuid:       Django ticket UUID
        fan_wallet_address: Fan's ERC-4337 smart wallet address
        amount_cents:      Ticket price in USD cents (e.g. 1000 = $10)

    Returns: tx hash string
    """
    vault     = get_payout_vault()
    event_id  = uuid_to_bytes32(event_uuid)
    ticket_id = uuid_to_bytes32(ticket_uuid)
    fan       = to_checksum_address(fan_wallet_address)
    amount    = usd_cents_to_usdc_units(amount_cents)

    logger.info(
        "contracts: deposit event=%s ticket=%s fan=%s amount_cents=%s",
        event_uuid, ticket_uuid, fan, amount_cents
    )

    receipt = submit_tx(
        vault.functions.deposit(event_id, ticket_id, fan, amount)
    )
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: deposit confirmed tx=%s", tx_hash)
    return tx_hash


def call_set_refundable(event_uuid: uuid.UUID) -> str:
    """
    Mark event as refundable (cancellation).
    O(1) gas — fans pull their own refunds via call_claim_refund().

    Returns: tx hash string
    """
    vault    = get_payout_vault()
    event_id = uuid_to_bytes32(event_uuid)

    logger.info("contracts: set_refundable event=%s", event_uuid)

    receipt = submit_tx(vault.functions.setRefundable(event_id))
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: set_refundable confirmed tx=%s", tx_hash)
    return tx_hash


def call_claim_refund(
    event_uuid: uuid.UUID,
    ticket_uuid: uuid.UUID,
) -> str:
    """
    Claim 100% refund for a single ticket after event cancellation.
    Django-initiated (Celery sub-task per fan).
    Gas sponsored by Base Paymaster — fan pays nothing.

    Returns: tx hash string
    """
    vault     = get_payout_vault()
    event_id  = uuid_to_bytes32(event_uuid)
    ticket_id = uuid_to_bytes32(ticket_uuid)

    logger.info(
        "contracts: claim_refund event=%s ticket=%s",
        event_uuid, ticket_uuid
    )

    receipt = submit_tx(
        vault.functions.claimRefund(event_id, ticket_id)
    )
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: claim_refund confirmed tx=%s", tx_hash)
    return tx_hash


def call_refund_one(ticket_uuid: uuid.UUID) -> str:
    """
    Refund a single ticket at 100% — used for postponement opt-out.
    Called within the 48h opt-out window after event postponement.

    Returns: tx hash string
    """
    vault     = get_payout_vault()
    ticket_id = uuid_to_bytes32(ticket_uuid)

    logger.info("contracts: refund_one ticket=%s", ticket_uuid)

    receipt = submit_tx(vault.functions.refundOne(ticket_id))
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: refund_one confirmed tx=%s", tx_hash)
    return tx_hash


def query_payout_unlock_time(event_uuid: uuid.UUID) -> int:
    """Return Unix timestamp when vendor can call claimPayout()."""
    vault    = get_payout_vault()
    event_id = uuid_to_bytes32(event_uuid)
    return call_view(vault.functions.payoutUnlockTime(event_id))


def query_event_state(event_uuid: uuid.UUID) -> dict:
    """Read event state from PayoutVault (no gas)."""
    vault    = get_payout_vault()
    event_id = uuid_to_bytes32(event_uuid)
    result   = call_view(vault.functions.getEvent(event_id))

    return {
        "kickoff":          result[0],
        "vendor":           result[1],
        "refundable":       result[2],
        "payout_claimed":   result[3],
        "vendor_claimable": result[4],
        "total_deposited":  result[5],
    }


# ── BuybackPool callers ───────────────────────────────────────────────────────

def call_request_buyback(
    event_uuid: uuid.UUID,
    ticket_uuid: uuid.UUID,
    fan_wallet_address: str,
    ticket_type: str,
) -> str:
    """
    Process a full buyback:
      - Calls PayoutVault.markReturned() via BuybackPool
      - Pays fan 90%/80%, treasury gets 10%/20%
      - Zeroes vendor claimable for this ticket

    Called by submit_buyback Celery sub-task after:
      1. DB ticket status set to 'returned'
      2. BuybackRecord created in DB

    Args:
        event_uuid:        Django event UUID
        ticket_uuid:       Django ticket UUID (or group_id for group buybacks)
        fan_wallet_address: Fan's ERC-4337 smart wallet
        ticket_type:       'single' or 'group'

    Returns: tx hash string
    """
    pool      = get_buyback_pool()
    event_id  = uuid_to_bytes32(event_uuid)
    ticket_id = uuid_to_bytes32(ticket_uuid)
    fan       = to_checksum_address(fan_wallet_address)
    ttype     = get_ticket_type_enum(ticket_type)

    logger.info(
        "contracts: request_buyback event=%s ticket=%s fan=%s type=%s",
        event_uuid, ticket_uuid, fan, ticket_type
    )

    receipt = submit_tx(
        pool.functions.requestBuyback(event_id, ticket_id, fan, ttype)
    )
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: request_buyback confirmed tx=%s", tx_hash)
    return tx_hash


def call_deposit_resale(
    ticket_uuid: uuid.UUID,
    amount_cents: int,
    vendor_wallet_address: str,
    new_buyer_wallet_address: str,
) -> str:
    """
    Accept resale payment and immediately distribute 40/60.
    Called after on-ramp partner confirms the new buyer's $110 payment.
    No T+48h lock — vendor receives 60% immediately.

    Args:
        ticket_uuid:             Django ticket UUID
        amount_cents:            Resale price in USD cents (110% of original)
        vendor_wallet_address:   Vendor's smart wallet (receives 60%)
        new_buyer_wallet_address: New buyer's smart wallet (for record keeping)

    Returns: tx hash string
    """
    pool      = get_buyback_pool()
    ticket_id = uuid_to_bytes32(ticket_uuid)
    amount    = usd_cents_to_usdc_units(amount_cents)
    vendor    = to_checksum_address(vendor_wallet_address)
    new_buyer = to_checksum_address(new_buyer_wallet_address)

    logger.info(
        "contracts: deposit_resale ticket=%s amount_cents=%s vendor=%s",
        ticket_uuid, amount_cents, vendor
    )

    receipt = submit_tx(
        pool.functions.depositResale(ticket_id, amount, vendor, new_buyer)
    )
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: deposit_resale confirmed tx=%s", tx_hash)
    return tx_hash


def call_record_return(ticket_uuid: uuid.UUID) -> str:
    """
    Emit on-chain proof of ticket ownership transfer.
    Called by activate_relist Celery task.

    Returns: tx hash string
    """
    pool      = get_buyback_pool()
    ticket_id = uuid_to_bytes32(ticket_uuid)

    logger.info("contracts: record_return ticket=%s", ticket_uuid)

    receipt = submit_tx(pool.functions.recordReturn(ticket_id))
    tx_hash = receipt["transactionHash"].hex()
    logger.info("contracts: record_return confirmed tx=%s", tx_hash)
    return tx_hash


def query_pool_balance() -> int:
    """Return BuybackPool USDC balance in USDC units (6 decimals)."""
    pool = get_buyback_pool()
    return call_view(pool.functions.poolBalance())


def query_pool_balance_cents() -> int:
    """Return BuybackPool balance in USD cents for admin dashboard display."""
    from .encoder import usdc_units_to_usd_cents
    return usdc_units_to_usd_cents(query_pool_balance())
