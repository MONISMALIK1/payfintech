"""
Idempotency tests.

Proves:
1. Same key replayed returns the SAME response body (byte-for-byte)
2. No duplicate payout is created on replay
3. No duplicate ledger entries on replay
4. Same key with DIFFERENT params is rejected (409 conflict)
5. Race condition: two threads with same key — exactly one creates the payout,
   the other gets a 200 replay
6. Same key across DIFFERENT merchants is allowed (key is scoped per merchant)
"""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections

from apps.payouts.service import create_payout
from apps.payouts.exceptions import IdempotencyConflictError
from apps.payouts.models import Payout, IdempotencyRecord
from apps.ledger.models import LedgerEntry, LedgerEntryType


pytestmark = pytest.mark.django_db(transaction=True)


def _close_connections():
    for conn in connections.all():
        conn.close()


class TestIdempotencyReplay:
    def test_same_key_returns_same_response(self, seeded_setup):
        merchant, bank_account = seeded_setup
        key = str(uuid.uuid4())

        body1, status1 = create_payout(
            merchant=merchant,
            bank_account_id=str(bank_account.id),
            amount_paise=50_000,
            idempotency_key=key,
        )
        assert status1 == 201

        body2, status2 = create_payout(
            merchant=merchant,
            bank_account_id=str(bank_account.id),
            amount_paise=50_000,
            idempotency_key=key,
        )
        assert status2 == 200, "Replay must return 200, not 201"
        assert body1 == body2, "Replay body must equal original body"

    def test_replay_does_not_create_second_payout(self, seeded_setup):
        merchant, bank_account = seeded_setup
        key = str(uuid.uuid4())

        for _ in range(5):
            create_payout(
                merchant=merchant,
                bank_account_id=str(bank_account.id),
                amount_paise=10_000,
                idempotency_key=key,
            )

        # Exactly ONE payout, ONE hold, ONE idempotency record
        assert Payout.objects.filter(merchant=merchant).count() == 1
        assert (
            LedgerEntry.objects.filter(
                merchant=merchant, entry_type=LedgerEntryType.PAYOUT_HOLD
            ).count()
            == 1
        )
        assert IdempotencyRecord.objects.filter(merchant=merchant).count() == 1

    def test_same_key_different_amount_is_conflict(self, seeded_setup):
        merchant, bank_account = seeded_setup
        key = str(uuid.uuid4())

        create_payout(
            merchant=merchant,
            bank_account_id=str(bank_account.id),
            amount_paise=10_000,
            idempotency_key=key,
        )

        with pytest.raises(IdempotencyConflictError):
            create_payout(
                merchant=merchant,
                bank_account_id=str(bank_account.id),
                amount_paise=20_000,  # different amount, same key
                idempotency_key=key,
            )

    def test_same_key_different_merchant_is_allowed(self, seeded_setup, db):
        """Idempotency is scoped per merchant — two merchants can use the same key."""
        from apps.accounts.models import Merchant, BankAccount

        merchant_a, bank_a = seeded_setup
        merchant_b = Merchant.objects.create(
            name="B", email=f"b-{uuid.uuid4()}@x.com"
        )
        bank_b = BankAccount.objects.create(
            merchant=merchant_b,
            account_holder_name="B Holder",
            account_number="999",
            ifsc_code="HDFC0001234",
        )
        LedgerEntry.objects.create(
            merchant=merchant_b,
            amount_paise=100_000,
            entry_type=LedgerEntryType.PAYMENT_RECEIVED,
            idempotency_key=f"seed-{merchant_b.id}",
        )

        same_key = str(uuid.uuid4())

        _, s1 = create_payout(
            merchant=merchant_a,
            bank_account_id=str(bank_a.id),
            amount_paise=10_000,
            idempotency_key=same_key,
        )
        _, s2 = create_payout(
            merchant=merchant_b,
            bank_account_id=str(bank_b.id),
            amount_paise=10_000,
            idempotency_key=same_key,
        )

        assert s1 == 201 and s2 == 201, "Same key, different merchant → both create"
        assert Payout.objects.filter(merchant=merchant_a).count() == 1
        assert Payout.objects.filter(merchant=merchant_b).count() == 1


class TestIdempotencyConcurrency:
    def test_concurrent_same_key_only_one_payout(self, seeded_setup):
        """
        Two threads call create_payout with the SAME key at the same instant.
        Both pass the read-side idempotency check, both enter the transaction,
        but only ONE INSERT into idempotency_records will succeed (UNIQUE constraint).
        The other catches IntegrityError and replays.

        Outcome: exactly ONE payout exists, both calls return the same body.
        """
        merchant, bank_account = seeded_setup
        key = str(uuid.uuid4())
        barrier = threading.Barrier(2)

        def attempt():
            barrier.wait()
            try:
                body, status = create_payout(
                    merchant=merchant,
                    bank_account_id=str(bank_account.id),
                    amount_paise=10_000,
                    idempotency_key=key,
                )
                return (status, body)
            finally:
                _close_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]  # submit all first
            results = [f.result() for f in futures]              # then collect

        # One returned 201 (creator), one returned 200 (replay) — OR both 200
        # if the second arrived after first committed
        statuses = sorted([r[0] for r in results])
        assert statuses in ([200, 201], [200, 200]), (
            f"Unexpected status combination: {statuses}"
        )

        # Bodies must be identical regardless of who won
        assert results[0][1] == results[1][1], (
            "Both responses must be byte-equal"
        )

        # Exactly one payout, one hold, one idempotency record
        assert Payout.objects.filter(merchant=merchant).count() == 1
        assert (
            LedgerEntry.objects.filter(
                merchant=merchant, entry_type=LedgerEntryType.PAYOUT_HOLD
            ).count()
            == 1
        )
        assert IdempotencyRecord.objects.filter(merchant=merchant).count() == 1
