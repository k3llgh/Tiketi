"""
Tenant URL conf — loaded for every subdomain tenant (e.g. kasarani.tiketi.co).
Public schema uses config/urls_public.py.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),

    # Fan-facing
    path("", include("apps.events.urls", namespace="events")),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("tickets/", include("apps.tickets.urls", namespace="tickets")),
    path("wallet/", include("apps.wallet.urls", namespace="wallet")),
    path("buyback/", include("apps.buyback.urls", namespace="buyback")),

    # Gate (low-bandwidth, offline-capable)
    path("gate/", include("apps.gate.urls", namespace="gate")),

    # Webhooks (no CSRF — verified by signature)
    path("webhooks/", include("apps.payments.urls", namespace="payments")),

    # Notifications in-app
    path("notifications/", include("apps.notifications.urls", namespace="notifications")),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
