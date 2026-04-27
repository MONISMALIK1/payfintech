import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Merchant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "merchants", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="BankAccount",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bank_accounts", to="accounts.merchant")),
                ("account_holder_name", models.CharField(max_length=255)),
                ("account_number", models.CharField(max_length=20)),
                ("ifsc_code", models.CharField(max_length=11)),
                ("account_type", models.CharField(
                    choices=[("savings", "Savings"), ("current", "Current")],
                    default="savings",
                    max_length=10,
                )),
                ("is_verified", models.BooleanField(default=False)),
                ("is_primary", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "bank_accounts"},
        ),
        migrations.AddIndex(
            model_name="bankaccount",
            index=models.Index(fields=["merchant", "is_primary"], name="bank_accounts_merchant_primary_idx"),
        ),
    ]
