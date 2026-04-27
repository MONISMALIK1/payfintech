"""
Custom exception handler for payout views.
Returns structured JSON for all API errors.
"""
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


class InsufficientFundsError(Exception):
    def __init__(self, available_paise: int, requested_paise: int):
        self.available_paise = available_paise
        self.requested_paise = requested_paise
        super().__init__(
            f"Available: {available_paise} paise. Requested: {requested_paise} paise."
        )


class PayoutValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class IdempotencyConflictError(Exception):
    def __init__(self, message: str = "Key used with different parameters."):
        self.message = message
        super().__init__(message)


def payout_exception_handler(exc, context):
    """
    Custom DRF exception handler.
    Catches domain errors and wraps them in consistent JSON responses.
    Falls back to DRF's default handler for everything else.
    """
    from apps.payouts.models import InvalidStateTransitionError

    if isinstance(exc, InsufficientFundsError):
        return Response(
            {
                "error": "insufficient_funds",
                "message": str(exc),
                "available_paise": exc.available_paise,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    if isinstance(exc, PayoutValidationError):
        return Response(
            {"error": "validation_error", "message": exc.message},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, IdempotencyConflictError):
        return Response(
            {"error": "idempotency_conflict", "message": exc.message},
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, InvalidStateTransitionError):
        return Response(
            {"error": "invalid_state_transition", "message": str(exc)},
            status=status.HTTP_409_CONFLICT,
        )

    # Fall back to DRF's built-in handler for validation errors, 404s, etc.
    response = exception_handler(exc, context)
    if response is not None:
        return response

    # Unhandled exception → 500
    return Response(
        {"error": "internal_error", "message": "An unexpected error occurred."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
