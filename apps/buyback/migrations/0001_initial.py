"""Initial migration for the buyback app."""
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("events", "0001_initial"),
        ("tickets", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="BuybackRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("group_id", models.UUIDField(db_index=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="buyback_records", to="events.event")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="buyback_records", to=settings.AUTH_USER_MODEL)),
                ("ticket_count", models.PositiveSmallIntegerField(default=1)),
                ("total_original_price_cents", models.PositiveIntegerField()),
                ("refund_amount_cents", models.PositiveIntegerField()),
                ("platform_retention_cents", models.PositiveIntegerField()),
                ("refund_rate", models.DecimalField(decimal_places=4, max_digits=5)),
                ("refund_status", models.CharField(choices=[("pending","Pending"),("completed","Completed"),("failed","Failed")], default="pending", max_length=20)),
                ("reference_id", models.CharField(blank=True, db_index=True, max_length=200)),
                ("error_message", models.TextField(blank=True)),
                ("requires_admin_approval", models.BooleanField(default=False)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_buybacks", to=settings.AUTH_USER_MODEL)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="buybackrecord", index=models.Index(fields=["user","event"], name="buyback_user_event_idx")),
        migrations.AddIndex(model_name="buybackrecord", index=models.Index(fields=["group_id"], name="buyback_group_idx")),
        migrations.CreateModel(
            name="RelistRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("ticket", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="relist_record", to="tickets.ticket")),
                ("buyback_record", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="relist_records", to="buyback.buybackrecord")),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="relist_records", to="events.event")),
                ("original_price_cents", models.PositiveIntegerField()),
                ("relist_price_cents", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("listed","Listed"),("sold","Sold"),("expired","Expired")], default="listed", max_length=10)),
                ("new_buyer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="relist_purchases", to=settings.AUTH_USER_MODEL)),
                ("sold_at", models.DateTimeField(blank=True, null=True)),
                ("sale_price_cents", models.PositiveIntegerField(blank=True, null=True)),
                ("platform_cut_cents", models.PositiveIntegerField(blank=True, null=True)),
                ("vendor_cut_cents", models.PositiveIntegerField(blank=True, null=True)),
                ("paystack_reference", models.CharField(blank=True, max_length=200)),
                ("listed_at", models.DateTimeField(auto_now_add=True)),
                ("expired_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-listed_at"]},
        ),
        migrations.AddIndex(model_name="relistrecord", index=models.Index(fields=["event","status"], name="relist_event_status_idx")),
    ]
