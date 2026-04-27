from django.urls import path
from .views import BalanceView, LedgerEntriesView

urlpatterns = [
    path("balance/", BalanceView.as_view(), name="balance"),
    path("ledger/", LedgerEntriesView.as_view(), name="ledger-entries"),
]
