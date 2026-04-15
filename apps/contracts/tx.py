"""
contracts/tx.py

Transaction building and submission layer.

All contract writes go through submit_tx(). It:
  1. Estimates gas with a safety buffer
  2. Signs with the platform signer key
  3. Broadcasts and waits for receipt
  4. Returns the tx hash on success

Retry logic lives in the Celery tasks (exponential backoff).
This module is synchronous — Celery runs it in a worker thread.
"""
import logging
import time

from web3.types import TxReceipt
from django.conf import settings

from .client import get_web3, get_platform_account

logger = logging.getLogger("tiketi.contracts.tx")

DEFAULT_GAS_MULTIPLIER = 1.2
DEFAULT_WAIT_TIMEOUT   = 120
DEFAULT_POLL_INTERVAL  = 2


class ContractCallError(Exception):
    """Raised when a contract call reverts or times out."""
    pass


def submit_tx(
    contract_fn,
    gas_multiplier: float = DEFAULT_GAS_MULTIPLIER,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
) -> TxReceipt:
    """
    Build, sign, broadcast, and wait for a contract transaction.

    Usage:
        vault = get_payout_vault()
        receipt = submit_tx(
            vault.functions.deposit(event_id, ticket_id, fan_addr, amount)
        )

    Returns TxReceipt on success.
    Raises ContractCallError on revert or timeout.
    """
    w3      = get_web3()
    account = get_platform_account()

    # 1. Estimate gas with safety buffer
    try:
        estimated_gas = contract_fn.estimate_gas({"from": account.address})
        gas_limit = int(estimated_gas * gas_multiplier)
    except Exception as exc:
        # Gas estimation fails on revert — surface the reason
        raise ContractCallError(
            f"Gas estimation failed (likely revert): {exc}"
        ) from exc

    # 2. Get current nonce
    nonce = w3.eth.get_transaction_count(account.address, "pending")

    # 3. Get gas price (Base uses EIP-1559)
    latest      = w3.eth.get_block("latest")
    base_fee    = latest.get("baseFeePerGas", w3.to_wei(0.001, "gwei"))
    priority    = w3.to_wei(0.001, "gwei")  # 0.001 gwei tip on Base
    max_fee     = base_fee + priority

    # 4. Build transaction
    tx = contract_fn.build_transaction({
        "from":                 account.address,
        "nonce":                nonce,
        "gas":                  gas_limit,
        "maxFeePerGas":         max_fee,
        "maxPriorityFeePerGas": priority,
        "chainId":              w3.eth.chain_id,
    })

    # 5. Sign
    signed = account.sign_transaction(tx)

    # 6. Broadcast
    try:
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        logger.info("tx broadcast hash=%s", tx_hash.hex())
    except Exception as exc:
        raise ContractCallError(f"Broadcast failed: {exc}") from exc

    # 7. Wait for receipt
    receipt = _wait_for_receipt(w3, tx_hash, wait_timeout)

    if receipt["status"] == 0:
        raise ContractCallError(
            f"Transaction reverted. hash={tx_hash.hex()}"
        )

    logger.info(
        "tx confirmed hash=%s block=%s gas_used=%s",
        tx_hash.hex(),
        receipt["blockNumber"],
        receipt["gasUsed"],
    )
    return receipt


def _wait_for_receipt(w3, tx_hash: bytes, timeout: int) -> TxReceipt:
    """Poll for transaction receipt until timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                return receipt
        except Exception:
            pass
        time.sleep(DEFAULT_POLL_INTERVAL)

    raise ContractCallError(
        f"Timed out waiting for receipt after {timeout}s. "
        f"hash={tx_hash.hex()}"
    )


def call_view(contract_fn):
    """
    Execute a read-only contract call (no gas, no signing).

    Usage:
        vault = get_payout_vault()
        event_data = call_view(vault.functions.getEvent(event_id_bytes))
    """
    try:
        return contract_fn.call()
    except Exception as exc:
        raise ContractCallError(f"View call failed: {exc}") from exc
