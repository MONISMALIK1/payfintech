import uuid
from django.db import models


class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "merchants"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class BankAccount(models.Model):
    SAVINGS = "savings"
    CURRENT = "current"
    ACCOUNT_TYPE_CHOICES = [(SAVINGS, "Savings"), (CURRENT, "Current")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.PROTECT, related_name="bank_accounts"
    )
    account_holder_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=20)
    ifsc_code = models.CharField(max_length=11)
    account_type = models.CharField(
        max_length=10, choices=ACCOUNT_TYPE_CHOICES, default=SAVINGS
    )
    is_verified = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bank_accounts"
        indexes = [models.Index(fields=["merchant", "is_primary"])]

    @property
    def account_number_masked(self) -> str:
        if len(self.account_number) <= 4:
            return self.account_number
        return "X" * (len(self.account_number) - 4) + self.account_number[-4:]
