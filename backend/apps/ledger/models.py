import uuid
from django.db import models
from django.db.models import CheckConstraint, Q


class LedgerEntryType(models.TextChoices):
    PAYMENT_RECEIVED = "payment_received", "Payment Received"
    PAYOUT_HOLD = "payout_hold", "Payout Hold"
    PAYOUT_RELEASE = "payout_release", "Payout Release"
    PAYOUT_COMPLETED = "payout_completed", "Payout Completed"
    FEE_DEBIT = "fee_debit", "Fee Debit"
    ADJUSTMENT_CREDIT = "adjustment_credit", "Adjustment Credit"
    ADJUSTMENT_DEBIT = "adjustment_debit", "Adjustment Debit"


class LedgerEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        "accounts.Merchant", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    amount_paise = models.BigIntegerField()
    entry_type = models.CharField(max_length=30, choices=LedgerEntryType.choices)
    payout = models.ForeignKey(
        "payouts.Payout",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    description = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ledger_entries"
        indexes = [
            models.Index(fields=["merchant", "-created_at"]),
            models.Index(fields=["merchant", "entry_type"]),
            models.Index(fields=["payout"]),
        ]
        constraints = [
            CheckConstraint(
                condition=~Q(amount_paise=0), name="ledger_amount_nonzero"
            ),
        ]

    def __str__(self):
        return f"{self.entry_type} {self.amount_paise} paise"

    @property
    def direction(self) -> str:
        return "credit" if self.amount_paise > 0 else "debit"
