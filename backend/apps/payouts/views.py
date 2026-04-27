"""
apps/payouts/views.py
=====================
Thin views. All business logic lives in service.py.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.accounts.models import Merchant
from .models import Payout
from .serializers import PayoutSerializer
from .service import create_payout
from .exceptions import (
    InsufficientFundsError,
    PayoutValidationError,
    IdempotencyConflictError,
)


def _get_merchant(request) -> Merchant | None:
    """Extract and resolve merchant from X-Merchant-Id header."""
    merchant_id = request.headers.get("X-Merchant-Id") or request.query_params.get("merchant_id")
    if not merchant_id:
        return None
    try:
        return Merchant.objects.get(id=merchant_id, is_active=True)
    except (Merchant.DoesNotExist, Exception):
        return None


class PayoutView(APIView):
    """
    POST /api/v1/payouts   — Create a payout
    GET  /api/v1/payouts/  — List payouts for a merchant
    """

    def post(self, request):
        # ── Headers ───────────────────────────────────────────────
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return Response(
                {
                    "error": "validation_error",
                    "message": "Idempotency-Key header is required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        merchant = _get_merchant(request)
        if not merchant:
            return Response(
                {
                    "error": "validation_error",
                    "message": "X-Merchant-Id header is required and must be a valid active merchant UUID.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Body ──────────────────────────────────────────────────
        amount_paise = request.data.get("amount_paise")
        bank_account_id = request.data.get("bank_account_id")

        if amount_paise is None or bank_account_id is None:
            return Response(
                {
                    "error": "validation_error",
                    "message": "Both amount_paise and bank_account_id are required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reject floats at the API layer
        if not isinstance(amount_paise, int):
            return Response(
                {
                    "error": "validation_error",
                    "message": "amount_paise must be an integer (no decimals).",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Delegate to service ───────────────────────────────────
        try:
            response_body, http_status = create_payout(
                merchant=merchant,
                bank_account_id=str(bank_account_id),
                amount_paise=amount_paise,
                idempotency_key=idempotency_key,
            )
            return Response(response_body, status=http_status)

        except InsufficientFundsError as exc:
            return Response(
                {
                    "error": "insufficient_funds",
                    "message": str(exc),
                    "available_paise": exc.available_paise,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        except PayoutValidationError as exc:
            return Response(
                {"error": "validation_error", "message": exc.message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IdempotencyConflictError as exc:
            return Response(
                {"error": "idempotency_conflict", "message": exc.message},
                status=status.HTTP_409_CONFLICT,
            )

    def get(self, request):
        merchant = _get_merchant(request)
        if not merchant:
            return Response(
                {
                    "error": "validation_error",
                    "message": "merchant_id query param or X-Merchant-Id header is required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            limit = int(request.query_params.get("limit", 50))
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            limit, offset = 50, 0

        status_filter = request.query_params.get("status")
        qs = Payout.objects.filter(merchant=merchant).order_by("-created_at")
        if status_filter:
            qs = qs.filter(status=status_filter)

        total_count = qs.count()
        payouts = qs.select_related("bank_account")[offset : offset + limit]

        serializer = PayoutSerializer(payouts, many=True)
        return Response({"count": total_count, "results": serializer.data})


class PayoutDetailView(APIView):
    """
    GET /api/v1/payouts/<payout_id>/
    """

    def get(self, request, payout_id):
        merchant = _get_merchant(request)
        if not merchant:
            return Response(
                {"error": "validation_error", "message": "X-Merchant-Id header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payout = Payout.objects.select_related("bank_account").get(
                id=payout_id, merchant=merchant
            )
        except Payout.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Payout not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = PayoutSerializer(payout)
        return Response(serializer.data)
