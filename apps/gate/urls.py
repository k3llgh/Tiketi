"""gate/urls.py"""
from django.urls import path
from . import views

app_name = "gate"

urlpatterns = [
    path("<uuid:event_id>/", views.gate_terminal_view, name="terminal"),
    path("<uuid:event_id>/validate/", views.validate_view, name="validate"),
    path("<uuid:event_id>/sync/", views.sync_view, name="sync"),
    path("<uuid:event_id>/sync/force/", views.force_sync_view, name="force_sync"),
]
