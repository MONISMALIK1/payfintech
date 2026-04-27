from rest_framework import serializers
from apps.accounts.serializers import BankAccountSerializer
from .models import Payout


class PayoutSerializer(serializers.ModelSerializer):
    amount_inr = serializers.SerializerMethodField()
    bank_account = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = [
            "id",
            "status",
            "amount_paise",
            "amount_inr",
            "bank_account",
            "attempt_count",
            "failure_reason",
            "bank_reference_id",
            "idempotency_key",
            "created_at",
            "updated_at",
            "processing_started_at",
            "completed_at",
            "failed_at",
        ]

    def get_amount_inr(self, obj) -> str:
        return f"₹{obj.amount_paise / 100:.2f}"

    def get_bank_account(self, obj) -> dict:
        ba = obj.bank_account
        return {
            "id": str(ba.id),
            "account_number_masked": ba.account_number_masked,
            "ifsc_code": ba.ifsc_code,
            "account_type": ba.account_type,
        }
