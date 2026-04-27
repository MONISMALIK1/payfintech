from rest_framework import serializers
from .models import LedgerEntry


class LedgerEntrySerializer(serializers.ModelSerializer):
    direction = serializers.ReadOnlyField()
    amount_inr = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "entry_type",
            "amount_paise",
            "amount_inr",
            "direction",
            "description",
            "payout_id",
            "created_at",
        ]

    def get_amount_inr(self, obj) -> str:
        return f"₹{abs(obj.amount_paise) / 100:.2f}"
