"""
Shared fixtures for payout tests.
Each test gets a fresh merchant + bank account + seed credit.
"""
import uuid
import pytest

from apps.accounts.models import Merchant, BankAccount
from apps.ledger.models import LedgerEntry, LedgerEntryType


@pytest.fixture
def merchant(db):
    """A fresh merchant with no ledger history."""
    return Merchant.objects.create(
        name="Test Merchant",
        email=f"test-{uuid.uuid4()}@example.com",
        is_active=True,
    )


@pytest.fixture
def bank_account(merchant):
    return BankAccount.objects.create(
        merchant=merchant,
        account_holder_name="Test Holder",
        account_number="1234567890",
        ifsc_code="HDFC0001234",
        account_type="current",
        is_verified=True,
        is_primary=True,
    )


@pytest.fixture
def seeded_merchant(merchant):
    """Merchant with ₹1,000 (100,000 paise) starting balance."""
    LedgerEntry.objects.create(
        merchant=merchant,
        amount_paise=100_000,
        entry_type=LedgerEntryType.PAYMENT_RECEIVED,
        idempotency_key=f"seed-{merchant.id}",
        description="Test seed credit",
    )
    return merchant


@pytest.fixture
def seeded_setup(seeded_merchant, bank_account):
    """Combined fixture: merchant with credit + a bank account."""
    return seeded_merchant, bank_account
