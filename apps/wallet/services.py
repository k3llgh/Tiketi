"""wallet/services.py"""
import logging
from django.db import transaction
from django.conf import settings

logger = logging.getLogger("tiketi.wallet")


def process_withdrawal(user, amount_cents: int) -> dict:
    from apps.wallet.models import Wallet, WalletTransaction
    cfg = settings.TIKETI
    if amount_cents <= 0:
        raise ValueError("Withdrawal amount must be positive.")
    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(user=user)
        if wallet.balance_cents < amount_cents:
            raise ValueError(
                f"Insufficient balance. Available: ${wallet.balance_cents/100:.2f}"
            )
        fee    = int(amount_cents * cfg["WITHDRAWAL_FEE_RATE"])
        payout = amount_cents - fee
        wallet.balance_cents -= amount_cents
        wallet.save(update_fields=["balance_cents","updated_at"])
        WalletTransaction.objects.create(
            wallet=wallet,
            amount_cents=-amount_cents,
            tx_type=WalletTransaction.TxType.WITHDRAWAL,
            description=f"Withdrawal ${amount_cents/100:.2f} (fee ${fee/100:.2f})",
        )
    logger.info("wallet: withdrawal user=%s amount=%s fee=%s payout=%s", user.id, amount_cents, fee, payout)
    return {"status":"pending","payout_cents":payout,"fee_cents":fee}
