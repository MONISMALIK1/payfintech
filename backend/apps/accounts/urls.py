from django.urls import path
from .views import MerchantListView

urlpatterns = [
    path("merchants/", MerchantListView.as_view(), name="merchant-list"),
]
