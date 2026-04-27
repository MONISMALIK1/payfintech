"""
apps/payouts/service.py
=======================
All payout business logic lives here. Views are thin; this module is thick.

Key invariants enforced here:
- Balance checked with SELECT FOR UPDATE (no race conditions)
- Payout + hold ledger entry created in one atomic transaction
- Idempotency record written in the same transaction
- No Python float arithmetic — all amounts stay as integer paise
"""
import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction, IntegrityError
from django.utils import timezone

from apps.accounts.models import Merchant, BankAccount
from apps.ledger.models import LedgerEntry, LedgerEntryType
from .models import Payout, PayoutStatus, IdempotencyRecord
from .exceptions import (
    InsufficientFundsError,
    PayoutValidationError,
    IdempotencyConflictError,
)

logger = logging.getLogger(__name__)


def _validate_payout_request(
    merchant: Merchant,
    bank_account_id: str,
    amount_paise: int,
) -> BankAccount:
    """
    Pre-flight checks before touching any financial records.
    Raises PayoutValidationError on any failure.
    Returns the validated BankAccount.
    """
    if not merchant.is_active:
        raise PayoutValidationError("Merchant account is inactive.")

    if not isinstance(amount_paise, int) or amount_paise <= 0:
        raise PayoutValidationError("amount_paise must be a positive integer.")

    try:
        bank_account = BankAccount.objects.get(id=bank_account_id, merchant=merchant)
    except BankAccount.DoesNotExist:
        raise PayoutValidationError(
            f"Bank account '{bank_account_id}' not found for this merchant."
        )

    return bank_account


def _check_idempotency(
    merchant: Merchant,
    idempotency_key: str,
    amount_paise: int,
    bank_account_id: str,
) -> IdempotencyRecord | None:
    """
    Check if we've seen this idempotency key before.

    Returns:
        IdempotencyRecord if this is a replay → caller returns cached response
        None if this is a new request
    Raises:
        IdempotencyConflictError if key was used with different params
    """
    window_start = timezone.now() - timedelta(
        hours=settings.PAYOUT_IDEMPOTENCY_WINDOW_HOURS
    )
    existing = IdempotencyRecord.objects.filter(
        merchant=merchant,
        idempotency_key=idempotency_key,
        created_at__gte=window_start,
    ).first()

    if existing:
        # Replay: check parameters match
        cached = existing.response_body
        if (
            cached.get("amount_paise") != amount_paise
            or cached.get("bank_account_id") != str(bank_account_id)
        ):
            raise IdempotencyConflictError(
                "Idempotency key was already used with different request parameters."
            )
        return existing

    return None


def create_payout(
    merchant: Merchant,
    bank_account_id: str,
    amount_paise: int,
    idempotency_key: str,
) -> tuple[dict, int]:
    """
    Create a payout request. Wraps the entire operation in one DB transaction.

    Returns:
        (response_dict, http_status_code)
        http_status_code is 201 for new payouts, 200 for idempotent replays.

    Raises:
        PayoutValidationError   → 400
        InsufficientFundsError  → 402
        IdempotencyConflictError → 409
    """
    # ── Validation (no DB writes yet) ──────────────────────────────
    bank_account = _validate_payout_request(merchant, bank_account_id, amount_paise)

    # ── Idempotency check (read-only) ──────────────────────────────
    existing = _check_idempotency(
        merchant, idempotency_key, amount_paise, bank_account_id
    )
    if existing:
        logger.info(
            "Idempotency replay: merchant=%s key=%s", merchant.id, idempotency_key
        )
        return existing.response_body, 200

    # ── Critical section: balance check + payout creation ──────────
    try:
        with transaction.atomic():
            from django.db.models import Sum

            # Step 1: acquire row-level locks on all existing merchant ledger entries.
            # IMPORTANT: select_for_update() is silently dropped by Django when chained
            # directly with .aggregate(), so we evaluate the queryset explicitly first
            # (via list()) to force the SELECT FOR UPDATE to actually execute and lock.
            # Once committed, the lock holds until the transaction ends.
            list(
                LedgerEntry.objects.select_for_update()
                .filter(merchant=merchant)
                .values("id")
            )

            # Step 2: compute balance — separate queries, but within the same
            # transaction that holds the row locks above.
            qs = LedgerEntry.objects.filter(merchant=merchant)
            total_paise = qs.aggregate(t=Sum("amount_paise"))["t"] or 0

            # Held = absolute of net negative hold entries
            net_hold = (
                qs.filter(
                    entry_type__in=[
                        LedgerEntryType.PAYOUT_HOLD,
                        LedgerEntryType.PAYOUT_RELEASE,
                    ]
                ).aggregate(h=Sum("amount_paise"))["h"]
                or 0
            )
            held_paise = abs(min(net_hold, 0))
            available_paise = total_paise - held_paise

            if available_paise < amount_paise:
                raise InsufficientFundsError(
                    available_paise=available_paise,
                    requested_paise=amount_paise,
                )

            # Create the payout record
            payout = Payout.objects.create(
                merchant=merchant,
                bank_account=bank_account,
                amount_paise=amount_paise,
                status=PayoutStatus.PENDING,
                idempotency_key=idempotency_key,
                max_attempts=settings.PAYOUT_MAX_RETRIES,
            )

            # Create the hold ledger entry (negative = debit)
            LedgerEntry.objects.create(
                merchant=merchant,
                amount_paise=-amount_paise,  # debit
                entry_type=LedgerEntryType.PAYOUT_HOLD,
                payout=payout,
                idempotency_key=f"hold-{payout.id}",
                description=f"Hold for payout {payout.id}",
            )

            response_body = _build_response(payout, bank_account)

            # Store idempotency record in the same transaction
            IdempotencyRecord.objects.create(
                merchant=merchant,
                idempotency_key=idempotency_key,
                response_body=response_body,
                http_status_code=201,
            )

    except IntegrityError:
        # Race condition: two concurrent requests with the same key both
        # pass the check above and race to INSERT IdempotencyRecord.
        # The loser hits the UNIQUE constraint → replay the winner's response.
        window_start = timezone.now() - timedelta(
            hours=settings.PAYOUT_IDEMPOTENCY_WINDOW_HOURS
        )
        existing = IdempotencyRecord.objects.filter(
            merchant=merchant,
            idempotency_key=idempotency_key,
            created_at__gte=window_start,
        ).first()
        if existing:
            return existing.response_body, 200
        raise  # genuine integrity error — re-raise

    # ── Enqueue Celery task outside the transaction ────────────────
    # We enqueue AFTER commit so the worker always finds the payout in DB.
    from .tasks import process_payout
    process_payout.delay(str(payout.id))

    logger.info(
        "Payout created: id=%s merchant=%s amount=%s paise",
        payout.id, merchant.id, amount_paise,
    )

    return response_body, 201


def _build_response(payout: Payout, bank_account: BankAccount) -> dict:
    return {
        "id": str(payout.id),
        "status": payout.status,
        "amount_paise": payout.amount_paise,
        "amount_inr": f"₹{payout.amount_paise / 100:.2f}",
        "bank_account_id": str(bank_account.id),
        "bank_account": {
            "id": str(bank_account.id),
            "account_number_masked": bank_account.account_number_masked,
            "ifsc_code": bank_account.ifsc_code,
        },
        "idempotency_key": payout.idempotency_key,
        "created_at": payout.created_at.isoformat() if payout.created_at else None,
    }
