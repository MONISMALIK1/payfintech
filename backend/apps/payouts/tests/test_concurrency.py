"""
Concurrency tests — the heart of the system.

These tests prove:
1. Two simultaneous payouts that would overdraft cannot both succeed
2. SELECT FOR UPDATE serializes the critical section
3. Concurrent successes from one merchant produce a consistent ledger

We use real threads against a real Postgres test DB (not mocked locks).
This catches race conditions that unit tests would miss entirely.
"""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from django.db import connections, transaction

from apps.payouts.service import create_payout
from apps.payouts.exceptions import InsufficientFundsError
from apps.payouts.models import Payout, PayoutStatus
from apps.ledger.models import LedgerEntry, LedgerEntryType


pytestmark = pytest.mark.django_db(transaction=True)
# transaction=True is REQUIRED — Django's normal test DB wraps each test in
# a single transaction, which would defeat SELECT FOR UPDATE between threads.


def _close_connections():
    """Each thread needs its own DB connection. Close them after each call."""
    for conn in connections.all():
        conn.close()


def _make_payout(merchant, bank_account, amount_paise, idempotency_key=None):
    """Wrapper that runs in a thread. Returns (status_code, response_or_exception)."""
    try:
        body, status = create_payout(
            merchant=merchant,
            bank_account_id=str(bank_account.id),
            amount_paise=amount_paise,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        return ("ok", status, body)
    except InsufficientFundsError as exc:
        return ("insufficient_funds", 402, {"available": exc.available_paise})
    except Exception as exc:
        return ("error", 500, {"exc": repr(exc)})
    finally:
        _close_connections()


class TestDoubleSpendPrevention:
    """
    The classic double-spend scenario:
    Merchant has ₹100. Two requests for ₹60 arrive simultaneously.
    Without locking, both would pass the balance check and overdraft.
    With SELECT FOR UPDATE, exactly one succeeds.
    """

    def test_two_concurrent_payouts_one_must_fail(self, seeded_setup):
        merchant, bank_account = seeded_setup
        # Merchant has ₹1,000 (100,000 paise). Two requests for ₹600 each.
        # Total demand = ₹1,200 — exceeds balance.
        # Exactly ONE must succeed, ONE must get InsufficientFunds.

        amount = 60_000  # ₹600 each
        results = []
        barrier = threading.Barrier(2)

        def attempt():
            barrier.wait()  # release both threads at the same instant
            return _make_payout(merchant, bank_account, amount)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            results = [f.result() for f in as_completed(futures)]

        outcomes = sorted([r[0] for r in results])
        assert outcomes == ["insufficient_funds", "ok"], (
            f"Expected exactly one ok and one insufficient_funds, got {outcomes}. "
            f"Full results: {results}"
        )

        # Ledger sanity: exactly ONE hold entry exists.
        holds = LedgerEntry.objects.filter(
            merchant=merchant, entry_type=LedgerEntryType.PAYOUT_HOLD
        )
        assert holds.count() == 1, "Exactly one hold should be recorded"
        assert holds.first().amount_paise == -amount

        # Balance never went negative
        from django.db.models import Sum

        total = (
            LedgerEntry.objects.filter(merchant=merchant)
            .aggregate(s=Sum("amount_paise"))["s"]
            or 0
        )
        # 100_000 (credit) + (-60_000) (one hold) = 40_000
        assert total == 40_000

    def test_ten_concurrent_payouts_only_some_succeed(self, seeded_setup):
        """
        Stress test: 10 threads, each requesting ₹150.
        Balance is ₹1,000 → at most 6 can succeed (₹900), the 7th-10th must fail.
        """
        merchant, bank_account = seeded_setup
        amount = 15_000  # ₹150 each
        n_threads = 10
        barrier = threading.Barrier(n_threads)

        def attempt():
            barrier.wait()
            return _make_payout(merchant, bank_account, amount)

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(attempt) for _ in range(n_threads)]
            results = [f.result() for f in as_completed(futures)]

        ok_count = sum(1 for r in results if r[0] == "ok")
        insufficient_count = sum(1 for r in results if r[0] == "insufficient_funds")

        # Total demand = 150_000, balance = 100_000 → max 6 successes
        assert ok_count <= 6, f"At most 6 should succeed, got {ok_count}"
        assert ok_count + insufficient_count == n_threads, (
            f"Every thread must terminate with ok or insufficient: {results}"
        )

        # Ledger invariant: total never negative
        from django.db.models import Sum

        total = (
            LedgerEntry.objects.filter(merchant=merchant)
            .aggregate(s=Sum("amount_paise"))["s"]
            or 0
        )
        assert total >= 0, f"Balance went negative: {total} paise"
        assert total == 100_000 - (ok_count * amount)

    def test_concurrent_different_merchants_dont_block(self, db):
        """
        Two merchants making payouts simultaneously must NOT serialize.
        SELECT FOR UPDATE scopes the lock to one merchant_id only.
        """
        from apps.accounts.models import Merchant, BankAccount

        merchants_and_accounts = []
        for i in range(2):
            m = Merchant.objects.create(
                name=f"M{i}", email=f"m{i}-{uuid.uuid4()}@x.com"
            )
            ba = BankAccount.objects.create(
                merchant=m,
                account_holder_name=f"H{i}",
                account_number=f"100000000{i}",
                ifsc_code="HDFC0001234",
            )
            LedgerEntry.objects.create(
                merchant=m,
                amount_paise=100_000,
                entry_type=LedgerEntryType.PAYMENT_RECEIVED,
                idempotency_key=f"seed-{m.id}",
            )
            merchants_and_accounts.append((m, ba))

        barrier = threading.Barrier(2)

        def go(pair):
            m, ba = pair
            barrier.wait()
            return _make_payout(m, ba, 50_000)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(go, merchants_and_accounts))

        # BOTH must succeed — different merchants don't contend
        assert all(r[0] == "ok" for r in results), (
            f"Different merchants must not block each other: {results}"
        )
