"""
contracts/encoder.py

Utility functions for encoding Django UUIDs and values into
the formats expected by the Solidity contracts.

Contracts use:
  - bytes32  for eventId and ticketId (keccak256 of UUID string)
  - uint256  for USDC amounts (6 decimal places)
  - address  for Ethereum addresses (checksummed)
"""
import uuid
from decimal import Decimal

from web3 import Web3


# ── ID encoding ───────────────────────────────────────────────────────────────

def uuid_to_bytes32(uid: uuid.UUID | str) -> bytes:
    """
    Convert a Django UUID to a bytes32 for use as eventId or ticketId.

    Strategy: keccak256 of the UUID string representation.
    This is deterministic, collision-resistant, and reversible via the DB.

    Example:
        uuid_to_bytes32("550e8400-e29b-41d4-a716-446655440000")
        → b'\\x...' (32 bytes)
    """
    uid_str = str(uid)
    return Web3.keccak(text=uid_str)


def bytes32_to_hex(b: bytes) -> str:
    """Convert bytes32 to 0x-prefixed hex string for logging/storage."""
    return "0x" + b.hex()


# ── Amount encoding ───────────────────────────────────────────────────────────

def usd_cents_to_usdc_units(cents: int) -> int:
    """
    Convert USD cents (our internal representation) to USDC units (6 decimals).

    Our DB stores prices as integer cents ($10.00 = 1000 cents).
    USDC uses 6 decimal places ($10.00 = 10_000_000 units).

    cents=1000 → 10_000_000 (multiply by 10_000)
    """
    return cents * 10_000


def usdc_units_to_usd_cents(units: int) -> int:
    """
    Convert USDC units (6 decimals) back to USD cents.
    10_000_000 → 1000 cents ($10.00)
    """
    return units // 10_000


def format_usdc_display(units: int) -> str:
    """Format USDC units as a human-readable USD string for display."""
    dollars = Decimal(units) / Decimal(1_000_000)
    return f"${dollars:.2f}"


# ── Address handling ──────────────────────────────────────────────────────────

def to_checksum_address(address: str) -> str:
    """Normalise any Ethereum address to EIP-55 checksum format."""
    return Web3.to_checksum_address(address)


def is_valid_address(address: str) -> bool:
    """Check if a string is a valid Ethereum address."""
    try:
        Web3.to_checksum_address(address)
        return True
    except (ValueError, TypeError):
        return False


# ── Ticket type encoding ──────────────────────────────────────────────────────

# BuybackPool.TicketType enum: SINGLE=0, GROUP=1
TICKET_TYPE_SINGLE = 0
TICKET_TYPE_GROUP  = 1


def get_ticket_type_enum(ticket_type: str) -> int:
    """
    Convert Django ticket_type string to Solidity TicketType enum int.
    'single' → 0, 'group' → 1
    """
    if ticket_type == "single":
        return TICKET_TYPE_SINGLE
    elif ticket_type == "group":
        return TICKET_TYPE_GROUP
    raise ValueError(f"Unknown ticket type: {ticket_type!r}")


# ── Stake tier encoding ────────────────────────────────────────────────────────

# StakeEscrow.Tier enum: NONE=0, SMALL=1, BIG=2
TIER_SMALL = 1
TIER_BIG   = 2


def get_tier_enum(vendor_tier: str) -> int:
    """Convert vendor tier string to Solidity Tier enum int."""
    if vendor_tier == "small":
        return TIER_SMALL
    elif vendor_tier == "big":
        return TIER_BIG
    raise ValueError(f"Unknown vendor tier: {vendor_tier!r}")
