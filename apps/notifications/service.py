"""notifications/service.py — SMS and email sending"""
import logging
from django.conf import settings

logger = logging.getLogger("tiketi.notifications")


def send_sms(phone: str, message: str) -> bool:
    cfg = settings.TIKETI
    api_key  = cfg.get("AT_API_KEY","")
    username = cfg.get("AT_USERNAME","sandbox")
    sender   = cfg.get("AT_SENDER_ID","TIKETI")
    if not api_key:
        logger.warning("notifications: AT_API_KEY not set, SMS skipped phone=%s", phone)
        return False
    try:
        import africastalking
        africastalking.initialize(username, api_key)
        sms = africastalking.SMS
        response = sms.send(message, [phone], sender)
        logger.info("notifications: SMS sent phone=%s status=%s", phone, response)
        return True
    except Exception as exc:
        logger.error("notifications: SMS failed phone=%s error=%s", phone, exc)
        return False


def send_email(to: str, subject: str, body: str) -> bool:
    from django.core.mail import send_mail
    from django.conf import settings as djsettings
    try:
        send_mail(subject, body, djsettings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        return True
    except Exception as exc:
        logger.error("notifications: email failed to=%s error=%s", to, exc)
        return False


def notify_vendor_payout_claimed(event_id_hex, vendor_address, amount_usdc, tx_hash):
    logger.info("notify: payout claimed event=%s vendor=%s amount=%s", event_id_hex, vendor_address, amount_usdc)


def notify_buyback_confirmed(ticket_id_hex, fan_address, refund_usdc, tx_hash):
    logger.info("notify: buyback confirmed ticket=%s fan=%s refund=%s", ticket_id_hex, fan_address, refund_usdc)
