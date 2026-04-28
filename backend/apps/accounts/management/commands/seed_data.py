"""
Management command: seed_data
Usage: python manage.py seed_data

Creates test merchants, bank accounts, and opening ledger credits.
Safe to run multiple times — fully idempotent via get_or_create.
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import Merchant, BankAccount
from apps.ledger.models import LedgerEntry, LedgerEntryType


SEED_DATA = [
    {
        "name": "Acme Exports Pvt Ltd",
        "email": "finance@acme-exports.in",
        "bank_accounts": [
            {
                "account_holder_name": "Acme Exports Pvt Ltd",
                "account_number": "1234567890123456",
                "ifsc_code": "HDFC0001234",
                "account_type": "current",
                "is_verified": True,
                "is_primary": True,
            },
            {
                "account_holder_name": "Acme Exports Pvt Ltd",
                "account_number": "9876543210654321",
                "ifsc_code": "ICIC0005678",
                "account_type": "savings",
                "is_verified": False,
                "is_primary": False,
            },
        ],
        "credits_paise": 1_000_000,  # ₹10,000
    },
    {
        "name": "GlobalTrade Solutions",
        "email": "accounts@globaltrade.co.in",
        "bank_accounts": [
            {
                "account_holder_name": "GlobalTrade Solutions",
                "account_number": "1111222233334444",
                "ifsc_code": "SBIN0009999",
                "account_type": "current",
                "is_verified": True,
                "is_primary": True,
            },
        ],
        "credits_paise": 500_000,  # ₹5,000
    },
]


class Command(BaseCommand):
    help = "Seed test merchants, bank accounts, and opening ledger credits."

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding test data...")

        for m_data in SEED_DATA:
            merchant, created = Merchant.objects.get_or_create(
                email=m_data["email"],
                defaults={"name": m_data["name"]},
            )
            action = "created" if created else "exists"
            self.stdout.write(f"  Merchant {action}: {merchant.name}")

            for ba_data in m_data["bank_accounts"]:
                BankAccount.objects.get_or_create(
                    merchant=merchant,
                    account_number=ba_data["account_number"],
                    defaults={
                        "account_holder_name": ba_data["account_holder_name"],
                        "ifsc_code": ba_data["ifsc_code"],
                        "account_type": ba_data["account_type"],
                        "is_verified": ba_data["is_verified"],
                        "is_primary": ba_data["is_primary"],
                    },
                )

            idem_key = f"seed-payment-{merchant.id}"
            if not LedgerEntry.objects.filter(idempotency_key=idem_key).exists():
                LedgerEntry.objects.create(
                    merchant=merchant,
                    amount_paise=m_data["credits_paise"],
                    entry_type=LedgerEntryType.PAYMENT_RECEIVED,
                    description=f"Initial seeded credit — ₹{m_data['credits_paise'] // 100:,}",
                    idempotency_key=idem_key,
                )
                self.stdout.write(
                    f"  Credited ₹{m_data['credits_paise'] // 100:,} to {merchant.name}"
                )

        self.stdout.write(self.style.SUCCESS("Seed complete."))
