from django.conf import settings


def tiketi_globals(request):
    """Inject platform-wide constants into every template."""
    return {
        "PLATFORM_NAME": "Tiketi",
        "PLATFORM_TAGLINE": "Africa's fraud-proof ticketing platform",
        "PAYSTACK_PUBLIC_KEY": settings.TIKETI["PAYSTACK_PUBLIC_KEY"],
        "GROUP_SIZE_CHOICES": settings.TIKETI["GROUP_SIZE_CHOICES"],
        "DEBUG": settings.DEBUG,
    }
