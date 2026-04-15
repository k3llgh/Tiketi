"""events/views.py"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django_htmx.http import HttpResponseClientRedirect


def index(request):
    """Homepage — list of upcoming active events."""
    from apps.events.models import Event
    events = (
        Event.objects.filter(status="active")
        .prefetch_related("seat_categories")
        .order_by("kickoff")[:20]
    )
    return render(request, "events/index.html", {"events": events})


def event_detail(request, event_id):
    """Event detail page — shows seat categories and triggers purchase modal."""
    from apps.events.models import Event
    event = get_object_or_404(Event, id=event_id, status__in=["active","postponed"])
    categories = event.seat_categories.all()
    return render(request, "events/detail.html", {
        "event": event,
        "categories": categories,
    })


def purchase_modal(request, event_id):
    """HTMX partial — the 4-click ticket purchase modal."""
    from apps.events.models import Event
    event = get_object_or_404(Event, id=event_id, status="active")
    categories = event.seat_categories.filter()
    from django.conf import settings
    group_sizes = settings.TIKETI["GROUP_SIZE_CHOICES"]
    return render(request, "events/partials/purchase_modal.html", {
        "event": event,
        "categories": categories,
        "group_sizes": group_sizes,
    })


@login_required
def create_event_view(request):
    """Vendor creates a new event."""
    if not request.user.is_vendor or not request.user.vendor_can_sell:
        return redirect("accounts:stake")
    if request.method == "POST":
        from apps.events.services import create_event
        from django.utils.dateparse import parse_datetime
        try:
            categories = []
            for cat in ["regular","vip","vvip"]:
                capacity = int(request.POST.get(f"{cat}_capacity",0))
                price    = int(request.POST.get(f"{cat}_price_cents",0))
                if capacity > 0 and price > 0:
                    categories.append({"category":cat,"capacity":capacity,"gross_price_cents":price})
            if not categories:
                raise ValueError("At least one seat category with capacity and price required.")
            event = create_event(
                vendor=request.user,
                home_team=request.POST["home_team"],
                away_team=request.POST["away_team"],
                kickoff=parse_datetime(request.POST["kickoff"]),
                venue=request.POST["venue"],
                competition=request.POST.get("competition",""),
                description=request.POST.get("description",""),
                categories=categories,
            )
            return redirect("events:event_detail", event_id=event.id)
        except Exception as exc:
            from django.contrib import messages
            messages.error(request, str(exc))
    return render(request, "events/create.html", {"cats": [("regular","Regular"),("vip","VIP"),("vvip","VVIP")]})


@login_required
@require_POST
def cancel_event_view(request, event_id):
    from apps.events.models import Event
    from apps.events.services import cancel_event_by_vendor
    event = get_object_or_404(Event, id=event_id, vendor=request.user)
    reason = request.POST.get("reason","")
    cancel_event_by_vendor(event, request.user, reason)
    return redirect("accounts:vendor_dashboard")


@login_required
@require_POST
def postpone_event_view(request, event_id):
    from apps.events.models import Event
    from apps.events.services import postpone_event
    from django.utils.dateparse import parse_datetime
    event = get_object_or_404(Event, id=event_id, vendor=request.user)
    new_kickoff = parse_datetime(request.POST["new_kickoff"])
    postpone_event(event, request.user, new_kickoff, request.POST.get("reason",""))
    return redirect("accounts:vendor_dashboard")
