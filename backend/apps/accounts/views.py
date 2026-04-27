from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Merchant
from .serializers import MerchantSerializer


class MerchantListView(APIView):
    """
    GET /api/v1/merchants/
    Returns all active merchants with their bank accounts.
    Used by the frontend to populate the merchant selector.
    """

    def get(self, request):
        merchants = Merchant.objects.prefetch_related("bank_accounts").filter(
            is_active=True
        )
        serializer = MerchantSerializer(merchants, many=True)
        return Response({"count": merchants.count(), "results": serializer.data})
