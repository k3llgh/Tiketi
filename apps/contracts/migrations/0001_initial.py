"""Initial migration for the contracts app."""
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="ChainTransaction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tx_type", models.CharField(
                    choices=[
                        ("set_kickoff","Set event kickoff"),("deposit","Ticket deposit"),
                        ("mark_returned","Ticket returned (buyback)"),("buyback","Buyback refund"),
                        ("set_refundable","Event cancellation — refundable"),("claim_refund","Fan refund claim"),
                        ("refund_one","Postpone opt-out refund"),("resale_deposit","Resale 40/60 distribution"),
                        ("record_return","Ownership transfer proof"),("slash","Vendor stake slash"),
                        ("force_majeure","Force majeure signal"),
                    ],
                    max_length=30,
                )),
                ("tx_hash", models.CharField(blank=True, db_index=True, max_length=66)),
                ("status", models.CharField(choices=[("pending","Pending"),("confirmed","Confirmed"),("failed","Failed")], default="pending", max_length=20)),
                ("error", models.TextField(blank=True)),
                ("retries", models.PositiveSmallIntegerField(default=0)),
                ("event_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("ticket_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("user_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("block_number", models.PositiveBigIntegerField(blank=True, null=True)),
                ("gas_used", models.PositiveBigIntegerField(blank=True, null=True)),
                ("amount_cents", models.PositiveBigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="chaintransaction", index=models.Index(fields=["tx_type","status"], name="chaintx_type_status_idx")),
        migrations.AddIndex(model_name="chaintransaction", index=models.Index(fields=["event_id","tx_type"], name="chaintx_event_type_idx")),
        migrations.AddIndex(model_name="chaintransaction", index=models.Index(fields=["ticket_id","tx_type"], name="chaintx_ticket_type_idx")),
    ]
