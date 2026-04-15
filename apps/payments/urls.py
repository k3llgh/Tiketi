"""payments/urls.py"""
from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("webhooks/paystack/", views.paystack_webhook, name="paystack_webhook"),
]
