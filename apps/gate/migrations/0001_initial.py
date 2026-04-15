"""Initial migration for the gate app."""
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="GateSyncLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("device_id", models.CharField(db_index=True, max_length=100)),
                ("event_id", models.UUIDField(blank=True, null=True)),
                ("synced_at", models.DateTimeField(auto_now_add=True)),
                ("ticket_count", models.PositiveIntegerField(default=0)),
                ("sync_status", models.CharField(choices=[("ok","Ok"),("stale","Stale"),("no_sync","Never synced")], default="ok", max_length=10)),
            ],
            options={"ordering": ["-synced_at"]},
        ),
        migrations.AddIndex(model_name="gatesynclog", index=models.Index(fields=["device_id","-synced_at"], name="gate_device_sync_idx")),
    ]
