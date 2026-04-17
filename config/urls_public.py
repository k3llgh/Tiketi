"""
Public schema URL conf — tiketi.co (the marketing / vendor onboarding site).
Tenant subdomains use config/urls.py.
"""
from django.urls import path, include

urlpatterns = [
    # Landing page, vendor signup, pricing
    path("", include("apps.accounts.urls_public", namespace="public")),
]
