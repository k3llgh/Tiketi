"""wallet/urls.py"""
from django.urls import path
from . import views

app_name = "wallet"

urlpatterns = [
    path("", views.wallet_view, name="wallet"),
    path("topup/", views.topup_view, name="topup"),
    path("withdraw/", views.withdraw_view, name="withdraw"),
]
