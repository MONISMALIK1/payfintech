"""
State machine tests.

Proves every transition rule in ALLOWED_TRANSITIONS is enforced:
    pending    → processing  ✅
    processing → completed   ✅
    processing → failed      ✅
    pending    → completed   ❌  (must be blocked — skips processing)
    pending    → failed      ❌  (must be blocked — skips processing)
    completed  → anything    ❌  (terminal state)
    failed     → anything    ❌  (terminal state, MOST IMPORTANT: failed→completed blocked)

The spec explicitly calls out: failed → completed must be BLOCKED.
"""
import pytest

from apps.payouts.models import Payout, PayoutStatus, InvalidStateTransitionError


pytestmark = pytest.mark.django_db


class TestAllowedTransitions:

    def _make_payout(self, merchant, bank_account, status):
        return Payout.objects.create(
            merchant=merchant,
            bank_account=bank_account,
            amount_paise=10_000,
            status=status,
            idempotency_key=f"sm-test-{status}-{merchant.id}",
        )

    def test_pending_to_processing_allowed(self, seeded_setup):
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.PENDING)
        p.transition_to(PayoutStatus.PROCESSING)  # must not raise
        assert p.status == PayoutStatus.PROCESSING

    def test_processing_to_completed_allowed(self, seeded_setup):
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.PROCESSING)
        p.transition_to(PayoutStatus.COMPLETED)
        assert p.status == PayoutStatus.COMPLETED

    def test_processing_to_failed_allowed(self, seeded_setup):
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.PROCESSING)
        p.transition_to(PayoutStatus.FAILED)
        assert p.status == PayoutStatus.FAILED


class TestBlockedTransitions:

    def _make_payout(self, merchant, bank_account, status):
        return Payout.objects.create(
            merchant=merchant,
            bank_account=bank_account,
            amount_paise=10_000,
            status=status,
            idempotency_key=f"sm-block-{status}-{merchant.id}",
        )

    def test_pending_to_completed_blocked(self, seeded_setup):
        """Cannot skip processing — pending → completed is not allowed."""
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.PENDING)
        with pytest.raises(InvalidStateTransitionError):
            p.transition_to(PayoutStatus.COMPLETED)

    def test_pending_to_failed_blocked(self, seeded_setup):
        """Cannot skip processing — pending → failed is not allowed."""
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.PENDING)
        with pytest.raises(InvalidStateTransitionError):
            p.transition_to(PayoutStatus.FAILED)

    def test_failed_to_completed_blocked(self, seeded_setup):
        """
        THE CRITICAL RULE from the spec:
        failed → completed MUST be blocked.

        In real systems this would allow reversing a failed payout as if it succeeded,
        creating funds from thin air without a matching bank transfer.
        """
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.FAILED)
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            p.transition_to(PayoutStatus.COMPLETED)
        assert "failed" in str(exc_info.value).lower()

    def test_failed_to_processing_blocked(self, seeded_setup):
        """Cannot retry a failed payout by recycling it — create a new payout instead."""
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.FAILED)
        with pytest.raises(InvalidStateTransitionError):
            p.transition_to(PayoutStatus.PROCESSING)

    def test_completed_to_failed_blocked(self, seeded_setup):
        """Cannot un-complete a payout — completed is terminal."""
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.COMPLETED)
        with pytest.raises(InvalidStateTransitionError):
            p.transition_to(PayoutStatus.FAILED)

    def test_completed_to_pending_blocked(self, seeded_setup):
        """Completed → pending would be nonsensical."""
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.COMPLETED)
        with pytest.raises(InvalidStateTransitionError):
            p.transition_to(PayoutStatus.PENDING)

    def test_pending_to_pending_blocked(self, seeded_setup):
        """Self-transition is not valid."""
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.PENDING)
        with pytest.raises(InvalidStateTransitionError):
            p.transition_to(PayoutStatus.PENDING)

    def test_transition_does_not_save_on_error(self, seeded_setup):
        """
        transition_to() must NOT persist an invalid transition.
        The payout status must remain unchanged after a failed call.
        """
        merchant, bank_account = seeded_setup
        p = self._make_payout(merchant, bank_account, PayoutStatus.FAILED)

        with pytest.raises(InvalidStateTransitionError):
            p.transition_to(PayoutStatus.COMPLETED)

        # Re-fetch from DB to confirm nothing was persisted
        p.refresh_from_db()
        assert p.status == PayoutStatus.FAILED
