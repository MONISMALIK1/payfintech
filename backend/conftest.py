"""
pytest configuration for the payout-engine backend.

Run with:
    cd backend && pytest

Tests live in apps/*/tests/test_*.py and use Django's test database
(automatically created and torn down).
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

# Import after Django setup
import pytest
import uuid

from apps.accounts.models import Merchant, BankAccount
from apps.ledger.models import LedgerEntry, LedgerEntryType


@pytest.fixture
def merchant(db):
    """Create a test merchant."""
    return Merchant.objects.create(
        name=f"Test Merchant {uuid.uuid4()}",
        email=f"test-{uuid.uuid4()}@example.com",
    )


@pytest.fixture
def bank_account(db, merchant):
    """Create a test bank account for the merchant."""
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
def seeded_setup(db):
    """
    Create a merchant with a bank account and seed ₹1,000 (100,000 paise).
    This is the default fixture for most tests.
    """
    merchant = Merchant.objects.create(
        name=f"Test Merchant {uuid.uuid4()}",
        email=f"test-{uuid.uuid4()}@example.com",
    )
    bank_account = BankAccount.objects.create(
        merchant=merchant,
        account_holder_name="Test Holder",
        account_number="1234567890",
        ifsc_code="HDFC0001234",
        account_type="current",
        is_verified=True,
        is_primary=True,
    )
    # Seed credit
    LedgerEntry.objects.create(
        merchant=merchant,
        amount_paise=100_000,  # ₹1,000
        entry_type=LedgerEntryType.PAYMENT_RECEIVED,
        idempotency_key=f"seed-{merchant.id}",
        description="Initial seed credit",
    )
    return merchant, bank_account
