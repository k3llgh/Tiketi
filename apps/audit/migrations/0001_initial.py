"""Initial migration for the audit app."""
import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.CharField(
                    choices=[
                        ("ticket_purchased","ticket_purchased"),("ticket_returned","ticket_returned"),
                        ("buyback_processed","buyback_processed"),("event_created","event_created"),
                        ("event_cancelled","event_cancelled"),("event_postponed","event_postponed"),
                        ("vendor_staked","vendor_staked"),("vendor_slashed","vendor_slashed"),
                        ("payout_claimed","payout_claimed"),("gate_admission","gate_admission"),
                        ("gate_denial","gate_denial"),
                    ],
                    db_index=True, max_length=50,
                )),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("ticket_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("event_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("amount_cents", models.PositiveBigIntegerField(blank=True, null=True)),
                ("chain_tx", models.CharField(blank=True, max_length=66)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("details", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="auditlog", index=models.Index(fields=["event_type","created_at"], name="audit_type_created_idx")),
    ]
