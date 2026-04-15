"""Initial migration for the tickets app."""
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("events", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tickets", to="events.event")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tickets", to=settings.AUTH_USER_MODEL)),
                ("seat_category", models.CharField(choices=[("regular","Regular"),("vip","VIP"),("vvip","VVIP")], max_length=10)),
                ("seat_number", models.PositiveIntegerField()),
                ("price_paid_cents", models.PositiveIntegerField()),
                ("booking_fee_cents", models.PositiveIntegerField()),
                ("totp_secret", models.CharField(max_length=64)),
                ("ticket_type", models.CharField(choices=[("single","Single"),("group","Group")], default="single", max_length=10)),
                ("group_id", models.UUIDField(db_index=True)),
                ("group_size", models.PositiveSmallIntegerField(default=1)),
                ("status", models.CharField(
                    choices=[("pending_payment","Pending payment"),("active","Active"),("returned","Returned (buyback)"),("relisted","Relisted (premium)"),("resold","Resold"),("expired","Expired"),("failed","Failed")],
                    db_index=True, default="pending_payment", max_length=16,
                )),
                ("relist_price_cents", models.PositiveIntegerField(blank=True, null=True)),
                ("relisted_at", models.DateTimeField(blank=True, null=True)),
                ("resold_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resold_tickets", to=settings.AUTH_USER_MODEL)),
                ("resold_at", models.DateTimeField(blank=True, null=True)),
                ("resold_totp_secret", models.CharField(blank=True, max_length=64)),
                ("postpone_refunded", models.BooleanField(default=False)),
                ("chain_tx", models.CharField(blank=True, max_length=66)),
                ("purchased_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddIndex(model_name="ticket", index=models.Index(fields=["event","status"], name="tickets_event_status_idx")),
        migrations.AddIndex(model_name="ticket", index=models.Index(fields=["user","status"], name="tickets_user_status_idx")),
        migrations.AddIndex(model_name="ticket", index=models.Index(fields=["group_id"], name="tickets_group_id_idx")),
        migrations.AddIndex(model_name="ticket", index=models.Index(fields=["totp_secret"], name="tickets_totp_secret_idx")),
        migrations.CreateModel(
            name="TicketEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="entries", to="tickets.ticket")),
                ("gate_id", models.CharField(max_length=50)),
                ("recorded_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("denied", models.BooleanField(default=False)),
                ("deny_reason", models.CharField(blank=True, max_length=100)),
            ],
            options={"ordering": ["recorded_at"]},
        ),
        migrations.AddIndex(model_name="ticketentry", index=models.Index(fields=["ticket","recorded_at"], name="ticketentry_ticket_idx")),
    ]
