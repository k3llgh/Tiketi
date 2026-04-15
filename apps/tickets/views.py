"""tickets/views.py"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django_htmx.http import HttpResponseClientRedirect


@login_required
@require_POST
def purchase_view(request, event_id):
    """Click 4 — confirm purchase. HTMX or redirect."""
    from apps.events.models import Event
    from apps.tickets.services import purchase_tickets, PurchaseError
    event    = get_object_or_404(Event, id=event_id, status="active")
    category = request.POST.get("category","regular")
    quantity = int(request.POST.get("quantity",1))
    try:
        tickets = purchase_tickets(user=request.user, event=event, category=category, quantity=quantity)
        if request.htmx:
            return render(request,"tickets/partials/purchase_success.html",{"tickets":tickets,"event":event})
        return redirect("tickets:ticket_list")
    except PurchaseError as exc:
        if request.htmx:
            return render(request,"tickets/partials/purchase_error.html",{"error":str(exc)})
        from django.contrib import messages
        messages.error(request, str(exc))
        return redirect("events:event_detail", event_id=event_id)


@login_required
def ticket_list_view(request):
    from apps.tickets.models import Ticket
    tickets = (
        Ticket.objects.filter(user=request.user)
        .select_related("event")
        .order_by("-purchased_at")
    )
    return render(request,"tickets/list.html",{"tickets":tickets})


@login_required
def ticket_detail_view(request, ticket_id):
    from apps.tickets.models import Ticket
    ticket = get_object_or_404(Ticket, id=ticket_id, user=request.user)
    return render(request,"tickets/detail.html",{"ticket":ticket})


@login_required
@require_POST
def postpone_opt_out_view(request, ticket_id):
    from apps.tickets.models import Ticket
    from apps.tickets.services import process_postpone_opt_out, PurchaseError
    ticket = get_object_or_404(Ticket, id=ticket_id, user=request.user)
    try:
        process_postpone_opt_out(ticket, request.user)
        if request.htmx:
            return render(request,"tickets/partials/opt_out_success.html")
        from django.contrib import messages
        messages.success(request,"Refund processed. Funds will appear in your wallet.")
        return redirect("tickets:ticket_list")
    except PurchaseError as exc:
        if request.htmx:
            return render(request,"tickets/partials/purchase_error.html",{"error":str(exc)})
        from django.contrib import messages
        messages.error(request,str(exc))
        return redirect("tickets:ticket_detail",ticket_id=ticket_id)
