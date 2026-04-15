"""wallet/views.py"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse


@login_required
def wallet_view(request):
    from apps.wallet.models import Wallet, WalletTransaction
    wallet = Wallet.objects.get_or_create(user=request.user)[0]
    transactions = WalletTransaction.objects.filter(wallet=wallet).order_by("-created_at")[:50]
    return render(request,"wallet/wallet.html",{"wallet":wallet,"transactions":transactions})


@login_required
@require_POST
def topup_view(request):
    """Initiate M-Pesa / card top-up via on-ramp partner."""
    amount_cents = int(request.POST.get("amount_cents", 0))
    if amount_cents < 100:
        return JsonResponse({"error":"Minimum top-up is $1.00"},status=400)
    # In production: call on-ramp partner API (Yellow Card / Kotani)
    # and redirect to their payment page. Here we return the intent.
    return JsonResponse({"status":"redirect","amount_cents":amount_cents})


@login_required
@require_POST
def withdraw_view(request):
    """Request wallet withdrawal to M-Pesa."""
    from apps.wallet.services import process_withdrawal
    amount_cents = int(request.POST.get("amount_cents",0))
    try:
        result = process_withdrawal(request.user, amount_cents)
        return JsonResponse(result)
    except Exception as exc:
        return JsonResponse({"error":str(exc)},status=400)
