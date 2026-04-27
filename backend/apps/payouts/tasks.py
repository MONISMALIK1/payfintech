"""
apps/payouts/tasks.py
=====================
Celery tasks for payout processing and recovery.

Key design decisions:
- acks_late=True: task not acknowledged until it completes.
  If the worker crashes mid-task, Celery re-delivers to another worker.
- SELECT FOR UPDATE in every state transition: prevents concurrent task
  instances from corrupting the same payout.
- Refund (payout_release) is always atomic with state=failed.
"""
import logging
import random
import string
import time

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)


class BankAPIError(Exception):
    """Raised when the simulated bank API rejects or times out."""
    pass


def _simulate_bank_api(amount_paise: int) -> str:
    """
    Simulated bank transfer API.
    Returns a bank reference ID on success.
    Raises BankAPIError on failure (configurable failure rate).
    """
    # Simulate network latency
    time.sleep(random.uniform(0.1, 0.5))

    failure_rate = getattr(settings, "PAYOUT_BANK_FAILURE_RATE", 0.2)
    if random.random() < failure_rate:
        raise BankAPIError("Bank API rejected the transfer (simulated failure).")

    # Return a fake bank reference ID
    ref = "BANK_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return ref


@shared_task(
    bind=True,
    name="apps.payouts.tasks.process_payout",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_payout(self, payout_id: str) -> dict:
    """
    Process a single payout.

    Steps:
    1. Load payout with SELECT FOR UPDATE
    2. Guard: must be in 'pending' status (prevents duplicate task runs)
    3. Transition to 'processing' → COMMIT (visible to beat recovery)
    4. Call simulated bank API
    5a. Success → transition to 'completed' + write completed ledger entry
    5b. Failure → retry (up to max_retries), then transition to 'failed' + release hold
    """
    from apps.payouts.models import Payout, PayoutStatus, InvalidStateTransitionError
    from apps.ledger.models import LedgerEntry, LedgerEntryType

    logger.info("Processing payout %s (attempt %d)", payout_id, self.request.retries + 1)

    # ── Step 1-3: Transition to processing ────────────────────────
    with transaction.atomic():
        try:
            payout = Payout.objects.select_for_update().get(id=payout_id)
        except Payout.DoesNotExist:
            logger.error("Payout %s not found — task abandoned.", payout_id)
            return {"status": "error", "reason": "payout_not_found"}

        # Guard: if already processing (e.g. recovered task), continue from here
        if payout.status == PayoutStatus.PROCESSING:
            logger.warning(
                "Payout %s already processing (attempt_count=%d) — continuing bank call.",
                payout_id, payout.attempt_count,
            )
        elif payout.status == PayoutStatus.PENDING:
            try:
                payout.transition_to(PayoutStatus.PROCESSING)
            except InvalidStateTransitionError as exc:
                logger.error("State transition error on payout %s: %s", payout_id, exc)
                return {"status": "error", "reason": str(exc)}

            payout.processing_started_at = timezone.now()
            payout.attempt_count = F("attempt_count") + 1
            payout.save(update_fields=["status", "processing_started_at", "attempt_count", "updated_at"])
        else:
            # Already completed or failed — no-op
            logger.info(
                "Payout %s already in terminal state %s — skipping.",
                payout_id, payout.status,
            )
            return {"status": "skipped", "payout_status": payout.status}

    # ── Step 4: Bank API call (outside transaction — can be slow) ──
    try:
        bank_ref = _simulate_bank_api(payout.amount_paise)
    except BankAPIError as exc:
        # ── Step 5b: Failure path ──────────────────────────────────
        logger.warning(
            "Bank API failed for payout %s (attempt %d/%d): %s",
            payout_id,
            self.request.retries + 1,
            settings.PAYOUT_MAX_RETRIES,
            exc,
        )

        # Reload to get real attempt_count (was set via F() above)
        payout.refresh_from_db()

        if payout.attempt_count < settings.PAYOUT_MAX_RETRIES:
            # Schedule retry with exponential backoff
            countdown_list = settings.PAYOUT_RETRY_COUNTDOWN_SECONDS
            countdown = countdown_list[min(self.request.retries, len(countdown_list) - 1)]
            logger.info(
                "Scheduling retry for payout %s in %ds (attempt %d/%d)",
                payout_id, countdown, payout.attempt_count + 1, settings.PAYOUT_MAX_RETRIES,
            )
            raise self.retry(exc=exc, countdown=countdown)
        else:
            # Max retries exhausted — mark failed and release funds atomically
            _mark_failed_and_release(payout, reason=str(exc))
            return {"status": "failed", "payout_id": payout_id}

    # ── Step 5a: Success path ──────────────────────────────────────
    _mark_completed(payout, bank_ref)
    logger.info("Payout %s completed. Bank ref: %s", payout_id, bank_ref)
    return {"status": "completed", "payout_id": payout_id, "bank_ref": bank_ref}


def _mark_completed(payout, bank_ref: str) -> None:
    """
    Atomically transition payout to 'completed' and write the settlement ledger entries.

    Two entries are written in the same transaction:

    1. payout_release (+amount) — cancels the payout_hold that was created at
       request time. Without this, the hold and the completed entry would both
       appear as debits, double-counting the merchant's deduction.

    2. payout_completed (-amount) — the permanent, irreversible debit that
       records the money leaving the merchant's account to the bank.

    Net effect on balance: +amount - amount = 0 change from the hold perspective;
    the permanent debit was already accounted for by the hold at request time.
    The release+completed pair makes the 'held' display go to zero and keeps
    SUM(amount_paise) correct for the available balance formula.

    Idempotency keys on both entries prevent duplicates if this function
    is called twice (e.g. worker restart after partial failure).
    """
    from apps.payouts.models import Payout, PayoutStatus, InvalidStateTransitionError
    from apps.ledger.models import LedgerEntry, LedgerEntryType

    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout.id)

        if payout.status != PayoutStatus.PROCESSING:
            logger.warning(
                "Cannot complete payout %s — unexpected status %s.",
                payout.id, payout.status,
            )
            return

        payout.transition_to(PayoutStatus.COMPLETED)
        payout.completed_at = timezone.now()
        payout.bank_reference_id = bank_ref
        payout.save(update_fields=["status", "completed_at", "bank_reference_id", "updated_at"])

        # Step 1: release the hold reservation (cancels the payout_hold debit)
        LedgerEntry.objects.get_or_create(
            idempotency_key=f"release-complete-{payout.id}",
            defaults={
                "merchant": payout.merchant,
                "amount_paise": +payout.amount_paise,   # positive = credits back the hold
                "entry_type": LedgerEntryType.PAYOUT_RELEASE,
                "payout": payout,
                "description": f"Hold released on payout completion {payout.id}",
            },
        )

        # Step 2: permanent debit — money has left to the bank
        LedgerEntry.objects.get_or_create(
            idempotency_key=f"completed-{payout.id}",
            defaults={
                "merchant": payout.merchant,
                "amount_paise": -payout.amount_paise,   # negative = permanent debit
                "entry_type": LedgerEntryType.PAYOUT_COMPLETED,
                "payout": payout,
                "description": f"Payout settled to bank (ref: {bank_ref})",
            },
        )


def _mark_failed_and_release(payout, reason: str) -> None:
    """
    Atomically transition payout to 'failed' and release the hold.
    The payout_release entry restores the merchant's available balance.
    Idempotency key on the release entry prevents double-release on retry.
    """
    from apps.payouts.models import Payout, PayoutStatus
    from apps.ledger.models import LedgerEntry, LedgerEntryType

    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout.id)

        if payout.status not in (PayoutStatus.PENDING, PayoutStatus.PROCESSING):
            logger.warning(
                "Cannot fail payout %s — already in terminal state %s.",
                payout.id, payout.status,
            )
            return

        # Force to processing first if still pending (edge case in recovery)
        if payout.status == PayoutStatus.PENDING:
            payout.transition_to(PayoutStatus.PROCESSING)

        payout.transition_to(PayoutStatus.FAILED)
        payout.failed_at = timezone.now()
        payout.failure_reason = reason
        payout.save(update_fields=["status", "failed_at", "failure_reason", "updated_at"])

        # Release the hold — positive amount restores available balance
        LedgerEntry.objects.get_or_create(
            idempotency_key=f"release-{payout.id}",
            defaults={
                "merchant": payout.merchant,
                "amount_paise": +payout.amount_paise,  # positive = credit / refund
                "entry_type": LedgerEntryType.PAYOUT_RELEASE,
                "payout": payout,
                "description": f"Refund for failed payout {payout.id}: {reason}",
            },
        )

    logger.info("Payout %s marked failed. Funds released.", payout.id)


@shared_task(name="apps.payouts.tasks.recover_stuck_payouts")
def recover_stuck_payouts() -> dict:
    """
    Beat task — runs every 30 seconds.

    Finds payouts stuck in 'processing' for longer than PAYOUT_PROCESSING_TIMEOUT_SECONDS
    and re-enqueues them.

    This recovers from:
    - Worker crash mid-task
    - Redis broker restart
    - Network partition between worker and DB
    """
    from apps.payouts.models import Payout, PayoutStatus

    timeout = settings.PAYOUT_PROCESSING_TIMEOUT_SECONDS
    cutoff = timezone.now() - timezone.timedelta(seconds=timeout)

    stuck = Payout.objects.filter(
        status=PayoutStatus.PROCESSING,
        processing_started_at__lt=cutoff,
        attempt_count__lt=F("max_attempts"),
    )

    recovered = 0
    for payout in stuck:
        logger.warning(
            "Recovering stuck payout %s (stuck since %s)",
            payout.id, payout.processing_started_at,
        )
        process_payout.delay(str(payout.id))
        recovered += 1

    if recovered:
        logger.info("Recovered %d stuck payouts.", recovered)

    return {"recovered": recovered}
