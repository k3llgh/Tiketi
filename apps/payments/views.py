"""payments/views.py — Paystack webhook"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("tiketi.payments")


@csrf_exempt
@require_POST
def paystack_webhook(request):
    """Verify Paystack webhook signature and process events."""
    secret = settings.TIKETI["PAYSTACK_WEBHOOK_SECRET"].encode()
    sig    = request.headers.get("X-Paystack-Signature","")
    digest = hmac.new(secret, request.body, hashlib.sha512).hexdigest()

    if not hmac.compare_digest(sig, digest):
        logger.warning("payments: invalid Paystack webhook signature")
        return HttpResponseForbidden("Invalid signature")

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error":"invalid json"},status=400)

    event_type = payload.get("event","")
    data       = payload.get("data",{})

    logger.info("payments: webhook event=%s", event_type)

    if event_type == "charge.success":
        _handle_charge_success(data)
    elif event_type == "transfer.success":
        _handle_transfer_success(data)
    elif event_type == "transfer.failed":
        _handle_transfer_failed(data)

    return JsonResponse({"status":"ok"})


def _handle_charge_success(data):
    """Fan top-up confirmed — credit wallet."""
    reference   = data.get("reference","")
    amount_kobo = data.get("amount",0)
    amount_cents = amount_kobo // 100  # Paystack uses kobo (1/100 of NGN) but we treat as cents
    logger.info("payments: charge success ref=%s amount=%s", reference, amount_cents)
    # TODO: credit fan wallet identified by reference
    # from apps.wallet.models import Wallet
    # wallet = Wallet.objects.get(topup_reference=reference)
    # wallet.credit(amount_cents, "Paystack top-up", reference)


def _handle_transfer_success(data):
    reference = data.get("reference","")
    logger.info("payments: transfer success ref=%s", reference)


def _handle_transfer_failed(data):
    reference = data.get("reference","")
    logger.info("payments: transfer failed ref=%s", reference)
