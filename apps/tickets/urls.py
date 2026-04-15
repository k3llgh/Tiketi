"""tickets/urls.py"""
from django.urls import path
from . import views

app_name = "tickets"

urlpatterns = [
    path("", views.ticket_list_view, name="ticket_list"),
    path("<uuid:ticket_id>/", views.ticket_detail_view, name="ticket_detail"),
    path("purchase/<uuid:event_id>/", views.purchase_view, name="purchase"),
    path("<uuid:ticket_id>/opt-out/", views.postpone_opt_out_view, name="postpone_opt_out"),
]
