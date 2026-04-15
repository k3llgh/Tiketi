"""buyback/urls.py"""
from django.urls import path
from . import views

app_name = "buyback"

urlpatterns = [
    path("request/<uuid:ticket_id>/", views.request_buyback_view, name="request_buyback"),
]
