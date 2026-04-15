"""accounts/urls_public.py — public schema routes (tiketi.co)"""
from django.urls import path
from . import views

app_name = "public"

urlpatterns = [
    path("", lambda r: __import__("django.shortcuts",fromlist=["render"]).render(r,"public/landing.html"), name="landing"),
    path("vendors/register/", views.register_vendor_view, name="register_vendor"),
    path("vendors/stake/", views.stake_view, name="stake"),
]
