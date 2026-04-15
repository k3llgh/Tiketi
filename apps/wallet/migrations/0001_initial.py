"""Initial migration for the wallet app."""
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="Wallet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="wallet", to=settings.AUTH_USER_MODEL)),
                ("balance_cents", models.PositiveBigIntegerField(default=0)),
                ("pending_cents", models.PositiveBigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="WalletTransaction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("wallet", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="wallet.wallet")),
                ("amount_cents", models.BigIntegerField()),
                ("tx_type", models.CharField(choices=[("credit","Credit"),("debit","Debit"),("pending","Pending"),("available","Available"),("failed","Failed"),("withdrawal","Withdrawal")], max_length=20)),
                ("description", models.CharField(max_length=300)),
                ("reference_id", models.CharField(blank=True, db_index=True, max_length=200)),
                ("available_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="wallettransaction", index=models.Index(fields=["wallet","tx_type","created_at"], name="wallettx_wallet_type_idx")),
        migrations.AddIndex(model_name="wallettransaction", index=models.Index(fields=["reference_id"], name="wallettx_ref_idx")),
    ]
