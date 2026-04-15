"""gate/views.py — gate terminal validation endpoint"""
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt


@login_required
def gate_terminal_view(request, event_id):
    """Gate terminal UI — staff enters 6-digit code."""
    from apps.events.models import Event
    from apps.gate.models import GateSyncLog
    event = Event.objects.get(id=event_id)
    sync  = GateSyncLog.latest_for_device(request.GET.get("device_id","default"))
    return render(request,"gate/terminal.html",{"event":event,"sync":sync})


@login_required
@require_POST
def validate_view(request, event_id):
    """Accept a 6-digit TOTP, run 3 checks, return admit/deny."""
    from apps.gate.services import validate_totp_and_admit
    code     = request.POST.get("code","").strip()
    gate_id  = request.POST.get("gate_id","G1")
    result   = validate_totp_and_admit(code, gate_id)
    if request.htmx:
        template = "gate/partials/admit.html" if result["admitted"] else "gate/partials/deny.html"
        return render(request, template, {"result":result,"ticket":result["ticket"]})
    return JsonResponse(result)


@login_required
def sync_view(request, event_id):
    """Return sync freshness status for this gate device."""
    from apps.gate.models import GateSyncLog
    device_id = request.GET.get("device_id","default")
    log = GateSyncLog.latest_for_device(device_id)
    if not log:
        status = "no_sync"
    elif log.is_stale():
        status = "stale"
    else:
        status = "ok"
    return JsonResponse({"status":status,"last_sync":log.synced_at.isoformat() if log else None})


@login_required
@require_POST
def force_sync_view(request, event_id):
    """Force-sync: pull delta of active ticket secrets since last sync."""
    from apps.events.models import Event
    from apps.tickets.models import Ticket
    from apps.gate.models import GateSyncLog
    from django.utils import timezone
    device_id = request.POST.get("device_id","default")
    event = Event.objects.get(id=event_id)
    tickets = Ticket.objects.filter(
        event=event, status__in=["active","resold"]
    ).values("id","totp_secret","resold_totp_secret","status","seat_category","seat_number")
    payload = [
        {
            "id": str(t["id"]),
            "active_totp_secret": t["resold_totp_secret"] or t["totp_secret"],
            "status": t["status"],
            "category": t["seat_category"],
            "seat": t["seat_number"],
        }
        for t in tickets
    ]
    # Server records the sync event
    GateSyncLog.objects.create(
        device_id=device_id,
        event_id=event_id,
        ticket_count=len(payload),
        sync_status="ok",
    )
    return JsonResponse({"status":"ok","tickets":payload,"count":len(payload)})
