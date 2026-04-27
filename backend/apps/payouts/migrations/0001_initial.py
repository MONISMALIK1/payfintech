import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Payout",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payouts", to="accounts.merchant")),
                ("bank_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payouts", to="accounts.bankaccount")),
                ("amount_paise", models.BigIntegerField()),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("processing", "Processing"),
                        ("completed", "Completed"),
                        ("failed", "Failed"),
                    ],
                    default="pending",
                    max_length=15,
                )),
                ("idempotency_key", models.CharField(max_length=100)),
                ("attempt_count", models.IntegerField(default=0)),
                ("max_attempts", models.IntegerField(default=3)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("processing_started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("failed_at", models.DateTimeField(blank=True, null=True)),
                ("failure_reason", models.TextField(blank=True, default="")),
                ("bank_reference_id", models.CharField(blank=True, default="", max_length=100)),
            ],
            options={"db_table": "payouts"},
        ),
        migrations.AddConstraint(
            model_name="payout",
            constraint=models.CheckConstraint(
                condition=models.Q(amount_paise__gt=0),
                name="payout_amount_positive",
            ),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["merchant", "status"], name="payouts_merchant_status_idx"),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["status", "created_at"], name="payouts_status_created_idx"),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["merchant", "idempotency_key"], name="payouts_merchant_idem_idx"),
        ),
        migrations.CreateModel(
            name="IdempotencyRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="idempotency_records", to="accounts.merchant")),
                ("idempotency_key", models.CharField(max_length=100)),
                ("response_body", models.JSONField()),
                ("http_status_code", models.IntegerField(default=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "idempotency_records"},
        ),
        migrations.AddConstraint(
            model_name="idempotencyrecord",
            constraint=models.UniqueConstraint(
                fields=["merchant", "idempotency_key"],
                name="idempotency_merchant_key_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="idempotencyrecord",
            index=models.Index(
                fields=["merchant", "idempotency_key", "created_at"],
                name="idempotency_merchant_key_idx",
            ),
        ),
    ]
