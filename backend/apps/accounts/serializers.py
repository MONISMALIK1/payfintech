from rest_framework import serializers
from .models import Merchant, BankAccount


class BankAccountSerializer(serializers.ModelSerializer):
    account_number_masked = serializers.ReadOnlyField()

    class Meta:
        model = BankAccount
        fields = [
            "id",
            "account_holder_name",
            "account_number_masked",
            "ifsc_code",
            "account_type",
            "is_verified",
            "is_primary",
            "created_at",
        ]


class MerchantSerializer(serializers.ModelSerializer):
    bank_accounts = BankAccountSerializer(many=True, read_only=True)

    class Meta:
        model = Merchant
        fields = ["id", "name", "email", "is_active", "created_at", "bank_accounts"]
