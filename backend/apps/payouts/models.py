import uuid
from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint


class PayoutStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


ALLOWED_TRANSITIONS = {
    PayoutStatus.PENDING: {PayoutStatus.PROCESSING},
    PayoutStatus.PROCESSING: {PayoutStatus.COMPLETED, PayoutStatus.FAILED},
    PayoutStatus.COMPLETED: set(),
    PayoutStatus.FAILED: set(),
}


class InvalidStateTransitionError(Exception):
    pass


class Payout(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        "accounts.Merchant", on_delete=models.PROTECT, related_name="payouts"
    )
    bank_account = models.ForeignKey(
        "accounts.BankAccount", on_delete=models.PROTECT, related_name="payouts"
    )
    amount_paise = models.BigIntegerField()
    status = models.CharField(
        max_length=15, choices=PayoutStatus.choices, default=PayoutStatus.PENDING
    )
    idempotency_key = models.CharField(max_length=100)
    attempt_count = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    failure_reason = models.TextField(blank=True, default="")
    bank_reference_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        db_table = "payouts"
        indexes = [
            models.Index(fields=["merchant", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["merchant", "idempotency_key"]),
        ]
        constraints = [
            CheckConstraint(condition=Q(amount_paise__gt=0), name="payout_amount_positive"),
        ]

    def __str__(self):
        return f"Payout {self.id} {self.status} {self.amount_paise}p"

    def transition_to(self, new_status: str) -> None:
        current = PayoutStatus(self.status)
        target = PayoutStatus(new_status)
        if target not in ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransitionError(
                f"Cannot transition payout {self.id} from {current} to {target}"
            )
        self.status = target


class IdempotencyRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        "accounts.Merchant",
        on_delete=models.PROTECT,
        related_name="idempotency_records",
    )
    idempotency_key = models.CharField(max_length=100)
    response_body = models.JSONField()
    http_status_code = models.IntegerField(default=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "idempotency_records"
        constraints = [
            UniqueConstraint(
                fields=["merchant", "idempotency_key"],
                name="idempotency_merchant_key_unique",
            )
        ]
        indexes = [
            models.Index(fields=["merchant", "idempotency_key", "created_at"]),
        ]
