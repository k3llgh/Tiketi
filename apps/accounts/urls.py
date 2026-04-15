"""accounts/urls.py"""
from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_fan_view, name="register_fan"),
    path("vendor/register/", views.register_vendor_view, name="register_vendor"),
    path("vendor/stake/", views.stake_view, name="stake"),
    path("vendor/dashboard/", views.vendor_dashboard_view, name="vendor_dashboard"),
    path("dashboard/", views.fan_dashboard_view, name="fan_dashboard"),
]
