"""gate/services.py — TOTP validation, 3-check logic, TicketEntry logging"""
import logging
import pyotp
from django.utils import timezone

logger = logging.getLogger("tiketi.gate")


class GateValidationError(Exception):
    def __init__(self, message, reason_code):
        super().__init__(message)
        self.reason_code = reason_code


def validate_totp_and_admit(totp_code: str, gate_id: str, event_date=None) -> dict:
    """
    Core gate validation logic.

    Searches for a ticket by TOTP code, runs 3 checks,
    logs a TicketEntry (admit or deny), and returns result.

    Returns dict:
        {"admitted": bool, "ticket": Ticket|None, "reason": str, "reason_code": str}
    """
    from apps.tickets.models import Ticket, TicketEntry

    if not totp_code or len(totp_code.strip()) != 6:
        return {"admitted": False, "ticket": None, "reason": "Invalid code format.", "reason_code": "invalid_format"}

    # Find ticket by TOTP — check both active and resold secrets
    ticket = _find_ticket_by_totp(totp_code.strip())

    if not ticket:
        return {"admitted": False, "ticket": None, "reason": "Code not recognised.", "reason_code": "not_found"}

    # Check 2: ticket status must be active or resold
    if ticket.status not in ("active","resold"):
        reason = _status_denial_reason(ticket.status)
        _log_entry(ticket, gate_id, denied=True, reason=reason)
        return {"admitted": False, "ticket": ticket, "reason": reason, "reason_code": f"status_{ticket.status}"}

    # Check 3: event date must be today
    today = (event_date or timezone.now()).date()
    if ticket.event.kickoff.date() != today:
        reason = f"This ticket is valid on {ticket.event.kickoff.strftime(\'%d %b %Y\')} only."
        _log_entry(ticket, gate_id, denied=True, reason=reason)
        return {"admitted": False, "ticket": ticket, "reason": reason, "reason_code": "wrong_date"}

    # All checks passed — admit and log
    _log_entry(ticket, gate_id, denied=False)
    logger.info("gate: admitted ticket=%s gate=%s", ticket.id, gate_id)
    return {"admitted": True, "ticket": ticket, "reason": "Admitted.", "reason_code": "ok"}


def _find_ticket_by_totp(code: str):
    """
    Find ticket whose active_totp_secret validates the given code.
    Searches active+resold tickets for today\'s events only (perf optimisation).
    """
    from apps.tickets.models import Ticket
    from django.conf import settings

    today = timezone.now().date()
    candidates = Ticket.objects.filter(
        event__kickoff__date=today,
        status__in=["active","resold"],
    ).select_related("event")

    window = settings.TIKETI.get("TOTP_VALID_WINDOW", 1)

    for ticket in candidates:
        secret = ticket.active_totp_secret
        totp   = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=window):
            return ticket

    return None


def _status_denial_reason(status: str) -> str:
    return {
        "pending_payment": "Ticket payment is still processing.",
        "returned":        "This ticket has been returned.",
        "relisted":        "This ticket is listed for resale.",
        "expired":         "This ticket has expired.",
        "failed":          "Ticket purchase failed. Please contact support.",
    }.get(status, f"Ticket is not valid (status: {status}).")


def _log_entry(ticket, gate_id: str, denied: bool, reason: str = ""):
    from apps.tickets.models import TicketEntry
    TicketEntry.objects.create(
        ticket=ticket,
        gate_id=gate_id,
        denied=denied,
        deny_reason=reason if denied else "",
    )
