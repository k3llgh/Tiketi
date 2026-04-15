"""events/urls.py"""
from django.urls import path
from . import views

app_name = "events"

urlpatterns = [
    path("", views.index, name="index"),
    path("events/<uuid:event_id>/", views.event_detail, name="event_detail"),
    path("events/<uuid:event_id>/modal/", views.purchase_modal, name="purchase_modal"),
    path("events/create/", views.create_event_view, name="create_event"),
    path("events/<uuid:event_id>/cancel/", views.cancel_event_view, name="cancel_event"),
    path("events/<uuid:event_id>/postpone/", views.postpone_event_view, name="postpone_event"),
]
