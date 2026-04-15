"""
contracts/client.py

web3.py singleton client. Loads contract ABIs and provides typed
contract instances for the three Tiketi contracts.

Usage:
    from apps.contracts.client import get_stake_escrow, get_payout_vault, get_buyback_pool
    escrow = get_stake_escrow()
    tx_hash = escrow.functions.slash(vendor_address, "vendor cancelled").transact(...)
"""
import json
import logging
from pathlib import Path
from functools import lru_cache
from typing import Optional

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from django.conf import settings

logger = logging.getLogger("tiketi.contracts")

# ── ABI loading ───────────────────────────────────────────────────────────────

ABI_DIR = Path(__file__).parent / "abis"


def _load_abi(name: str) -> list:
    path = ABI_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


# ── web3 client singleton ─────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_web3() -> Web3:
    """
    Return a cached Web3 instance connected to Base.
    Uses the RPC URL from settings.TIKETI_CONTRACTS.
    """
    cfg = _contract_config()
    rpc_url = cfg["RPC_URL"]

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))

    # Base is an OP Stack chain — inject POA middleware
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        logger.error("web3: cannot connect to Base RPC at %s", rpc_url)
        raise ConnectionError(f"Cannot connect to Base RPC: {rpc_url}")

    logger.info("web3: connected to Base chain_id=%s", w3.eth.chain_id)
    return w3


@lru_cache(maxsize=1)
def get_platform_account():
    """
    Return the platform signer account (hot wallet).
    This is the Django backend signer — NOT a user-facing wallet.
    Private key loaded from settings, never from environment directly in views.
    """
    cfg = _contract_config()
    w3 = get_web3()
    account = w3.eth.account.from_key(cfg["PLATFORM_PRIVATE_KEY"])
    logger.info("web3: platform signer loaded address=%s", account.address)
    return account


def _contract_config() -> dict:
    """Pull contract config from Django settings."""
    cfg = getattr(settings, "TIKETI_CONTRACTS", None)
    if not cfg:
        raise ImproperlyConfigured(
            "TIKETI_CONTRACTS not found in Django settings. "
            "Add it to settings.py with RPC_URL, contract addresses, "
            "and PLATFORM_PRIVATE_KEY."
        )
    return cfg


# ── Contract instances ────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_stake_escrow():
    """Return a typed StakeEscrow contract instance."""
    cfg = _contract_config()
    w3  = get_web3()
    return w3.eth.contract(
        address=Web3.to_checksum_address(cfg["STAKE_ESCROW_ADDRESS"]),
        abi=_load_abi("StakeEscrow"),
    )


@lru_cache(maxsize=1)
def get_payout_vault():
    """Return a typed PayoutVault contract instance."""
    cfg = _contract_config()
    w3  = get_web3()
    return w3.eth.contract(
        address=Web3.to_checksum_address(cfg["PAYOUT_VAULT_ADDRESS"]),
        abi=_load_abi("PayoutVault"),
    )


@lru_cache(maxsize=1)
def get_buyback_pool():
    """Return a typed BuybackPool contract instance."""
    cfg = _contract_config()
    w3  = get_web3()
    return w3.eth.contract(
        address=Web3.to_checksum_address(cfg["BUYBACK_POOL_ADDRESS"]),
        abi=_load_abi("BuybackPool"),
    )


# ── Missing import guard ──────────────────────────────────────────────────────

try:
    from django.core.exceptions import ImproperlyConfigured
except ImportError:
    class ImproperlyConfigured(Exception):
        pass
