"""Initial migration for the events app."""
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Event",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("vendor", models.ForeignKey(
                    limit_choices_to={"role": "vendor"},
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="events", to=settings.AUTH_USER_MODEL,
                )),
                ("home_team", models.CharField(max_length=150)),
                ("away_team", models.CharField(max_length=150)),
                ("competition", models.CharField(blank=True, max_length=100)),
                ("venue", models.CharField(max_length=200)),
                ("kickoff", models.DateTimeField()),
                ("description", models.TextField(blank=True)),
                ("poster", models.ImageField(blank=True, null=True, upload_to="event_posters/")),
                ("status", models.CharField(
                    choices=[
                        ("draft", "Draft"), ("under_review", "Under review"),
                        ("active", "Active"), ("paused", "Paused"),
                        ("postponed", "Postponed"), ("cancelled", "Cancelled"),
                        ("completed", "Completed"),
                    ],
                    db_index=True, default="draft", max_length=20,
                )),
                ("cancelled_by", models.CharField(
                    blank=True,
                    choices=[("vendor", "Vendor"), ("admin", "Admin (force majeure)")],
                    max_length=10, null=True,
                )),
                ("cancellation_reason", models.TextField(blank=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("stake_slashed", models.BooleanField(default=False)),
                ("postponed_from", models.DateTimeField(blank=True, null=True)),
                ("postpone_opt_out_deadline", models.DateTimeField(blank=True, null=True)),
                ("paused_at", models.DateTimeField(blank=True, null=True)),
                ("review_deadline", models.DateTimeField(blank=True, null=True)),
                ("review_requested_at", models.DateTimeField(blank=True, null=True)),
                ("review_approved_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="reviewed_events", to=settings.AUTH_USER_MODEL,
                )),
                ("review_approved_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("kickoff_tx", models.CharField(blank=True, max_length=66)),
                ("slash_tx", models.CharField(blank=True, max_length=66)),
                ("buyback_active", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-kickoff"]},
        ),
        migrations.AddIndex(
            model_name="event",
            index=models.Index(fields=["status", "kickoff"], name="events_status_kickoff_idx"),
        ),
        migrations.AddIndex(
            model_name="event",
            index=models.Index(fields=["vendor", "status"], name="events_vendor_status_idx"),
        ),

        migrations.CreateModel(
            name="SeatCategory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="seat_categories", to="events.event",
                )),
                ("category", models.CharField(
                    choices=[("regular", "Regular"), ("vip", "VIP"), ("vvip", "VVIP")],
                    max_length=10,
                )),
                ("capacity", models.PositiveIntegerField()),
                ("gross_price_cents", models.PositiveIntegerField()),
            ],
            options={"unique_together": {("event", "category")}},
        ),

        migrations.CreateModel(
            name="EventStatusLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="status_logs", to="events.event",
                )),
                ("from_status", models.CharField(max_length=20)),
                ("to_status", models.CharField(max_length=20)),
                ("changed_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["created_at"]},
        ),
    ]
