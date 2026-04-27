from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.ledger.urls")),
    path("api/v1/", include("apps.payouts.urls")),
]
