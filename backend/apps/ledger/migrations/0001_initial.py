import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("payouts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="LedgerEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ledger_entries", to="accounts.merchant")),
                ("amount_paise", models.BigIntegerField()),
                ("entry_type", models.CharField(
                    choices=[
                        ("payment_received", "Payment Received"),
                        ("payout_hold", "Payout Hold"),
                        ("payout_release", "Payout Release"),
                        ("payout_completed", "Payout Completed"),
                        ("fee_debit", "Fee Debit"),
                        ("adjustment_credit", "Adjustment Credit"),
                        ("adjustment_debit", "Adjustment Debit"),
                    ],
                    max_length=30,
                )),
                ("payout", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="ledger_entries",
                    to="payouts.payout",
                )),
                ("description", models.TextField(blank=True, default="")),
                ("idempotency_key", models.CharField(max_length=100, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "ledger_entries"},
        ),
        migrations.AddConstraint(
            model_name="ledgerentry",
            constraint=models.CheckConstraint(
                condition=~models.Q(amount_paise=0),
                name="ledger_amount_nonzero",
            ),
        ),
        migrations.AddIndex(
            model_name="ledgerentry",
            index=models.Index(fields=["merchant", "-created_at"], name="ledger_merchant_created_idx"),
        ),
        migrations.AddIndex(
            model_name="ledgerentry",
            index=models.Index(fields=["merchant", "entry_type"], name="ledger_merchant_type_idx"),
        ),
        migrations.AddIndex(
            model_name="ledgerentry",
            index=models.Index(fields=["payout"], name="ledger_payout_idx"),
        ),
    ]
