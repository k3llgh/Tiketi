"""buyback/views.py"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST


@login_required
@require_POST
def request_buyback_view(request, ticket_id):
    from apps.tickets.models import Ticket
    from apps.buyback.services import process_buyback, BuybackError

    ticket = get_object_or_404(Ticket, id=ticket_id, user=request.user)
    event  = ticket.event

    # For group tickets, get all tickets in the group
    if ticket.ticket_type == "group":
        tickets = list(
            Ticket.objects.filter(
                group_id=ticket.group_id,
                status__in=["active","resold"],
            )
        )
    else:
        tickets = [ticket]

    try:
        record = process_buyback(request.user, event, tickets)
        if request.htmx:
            from django_htmx.http import HttpResponseClientRedirect
            return HttpResponseClientRedirect("/tickets/")
        from django.contrib import messages
        messages.success(
            request,
            f"Buyback processed. ${record.refund_amount_cents/100:.2f} "
            f"will appear in your wallet shortly."
        )
        return redirect("tickets:ticket_list")
    except BuybackError as exc:
        if request.htmx:
            return render(request,"buyback/partials/buyback_error.html",{"error":str(exc)})
        from django.contrib import messages
        messages.error(request,str(exc))
        return redirect("tickets:ticket_detail",ticket_id=ticket_id)
