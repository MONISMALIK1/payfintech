from django.db.models import Sum, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.accounts.models import Merchant
from apps.payouts.models import PayoutStatus
from .models import LedgerEntry, LedgerEntryType
from .serializers import LedgerEntrySerializer


def _get_merchant_or_400(merchant_id: str):
    """
    Fetch a merchant by UUID or raise ValueError.
    Used in both views to avoid duplication.
    """
    if not merchant_id:
        raise ValueError("merchant_id query param is required.")
    try:
        return Merchant.objects.get(id=merchant_id, is_active=True)
    except Merchant.DoesNotExist:
        raise ValueError(f"Merchant '{merchant_id}' not found.")


class BalanceView(APIView):
    """
    GET /api/v1/balance/?merchant_id=<uuid>

    Returns available, held, and total balance.
    All amounts computed at DB level from ledger_entries — no stored balance column.
    """

    def get(self, request):
        merchant_id = request.query_params.get("merchant_id")
        try:
            merchant = _get_merchant_or_400(merchant_id)
        except ValueError as exc:
            return Response(
                {"error": "validation_error", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = LedgerEntry.objects.filter(merchant=merchant)

        # Total = sum of all entries (credits + debits)
        total_paise = qs.aggregate(t=Sum("amount_paise"))["t"] or 0

        # Held = absolute value of net hold/release entries
        # payout_hold entries are negative; payout_release are positive
        # Net of these two gives the current hold amount
        hold_qs = qs.filter(
            entry_type__in=[
                LedgerEntryType.PAYOUT_HOLD,
                LedgerEntryType.PAYOUT_RELEASE,
            ]
        )
        net_hold = hold_qs.aggregate(h=Sum("amount_paise"))["h"] or 0
        held_paise = abs(min(net_hold, 0))  # only negative net means active holds

        available_paise = total_paise - held_paise

        def fmt(paise: int) -> str:
            return f"₹{paise / 100:.2f}"

        return Response(
            {
                "merchant_id": str(merchant.id),
                "available_balance_paise": available_paise,
                "held_balance_paise": held_paise,
                "total_balance_paise": total_paise,
                "available_balance_inr": fmt(available_paise),
                "held_balance_inr": fmt(held_paise),
                "total_balance_inr": fmt(total_paise),
            }
        )


class LedgerEntriesView(APIView):
    """
    GET /api/v1/ledger/?merchant_id=<uuid>&limit=50&offset=0

    Returns paginated ledger entries for a merchant, newest first.
    """

    def get(self, request):
        merchant_id = request.query_params.get("merchant_id")
        try:
            merchant = _get_merchant_or_400(merchant_id)
        except ValueError as exc:
            return Response(
                {"error": "validation_error", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            limit = int(request.query_params.get("limit", 50))
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            return Response(
                {"error": "validation_error", "message": "limit and offset must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = LedgerEntry.objects.filter(merchant=merchant).order_by("-created_at")
        total_count = qs.count()
        entries = qs[offset : offset + limit]

        serializer = LedgerEntrySerializer(entries, many=True)
        return Response({"count": total_count, "results": serializer.data})
