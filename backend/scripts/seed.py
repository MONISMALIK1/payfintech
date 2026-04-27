"""
scripts/seed.py — Bootstrap test data for local development
===========================================================
Run with:
    python manage.py shell < scripts/seed.py

Creates:
  - 2 test merchants
  - 2 bank accounts per merchant (one primary)
  - Sufficient ledger credits so payouts can be tested immediately
"""
import uuid
from django.utils import timezone

from apps.accounts.models import Merchant, BankAccount
from apps.ledger.models import LedgerEntry, LedgerEntryType

print("=" * 55)
print("🌱  Seeding test data...")
print("=" * 55)

# ── Merchants ─────────────────────────────────────────────────────

merchants_data = [
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
        "credits_paise": 1_000_000,  # ₹10,000 starting balance
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
        "credits_paise": 500_000,  # ₹5,000 starting balance
    },
]

for m_data in merchants_data:
    merchant, created = Merchant.objects.get_or_create(
        email=m_data["email"],
        defaults={"name": m_data["name"]},
    )
    action = "Created" if created else "Already exists"
    print(f"\n  {action}: {merchant.name} ({merchant.id})")

    for ba_data in m_data["bank_accounts"]:
        ba, ba_created = BankAccount.objects.get_or_create(
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
        mark = "✓" if ba_created else "~"
        print(
            f"    {mark} Bank account: {ba.account_number_masked} "
            f"({ba.ifsc_code}) primary={ba.is_primary}"
        )

    # Seed a starting credit (simulated international payment received)
    credits_paise = m_data["credits_paise"]
    idem_key = f"seed-payment-{merchant.id}"
    if not LedgerEntry.objects.filter(idempotency_key=idem_key).exists():
        LedgerEntry.objects.create(
            merchant=merchant,
            amount_paise=credits_paise,
            entry_type=LedgerEntryType.PAYMENT_RECEIVED,
            description=f"Initial seeded credit — ₹{credits_paise // 100:,}",
            idempotency_key=idem_key,
        )
        print(
            f"    ✓ Credited: ₹{credits_paise // 100:,} "
            f"({credits_paise:,} paise)"
        )
    else:
        print(f"    ~ Credit already seeded.")

print("\n" + "=" * 55)
print("✅  Seed complete.")
print("=" * 55)
print("\nMerchant IDs for API testing:")
for m in Merchant.objects.all():
    ba = m.bank_accounts.filter(is_primary=True).first()
    print(f"\n  {m.name}")
    print(f"    Merchant ID  : {m.id}")
    if ba:
        print(f"    Bank Acct ID : {ba.id}  ({ba.account_number_masked})")
print()
