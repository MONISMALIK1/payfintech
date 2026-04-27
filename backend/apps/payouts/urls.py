from django.urls import path
from .views import PayoutView, PayoutDetailView

urlpatterns = [
    path("payouts/", PayoutView.as_view(), name="payout-list-create"),
    path("payouts/<uuid:payout_id>/", PayoutDetailView.as_view(), name="payout-detail"),
]
