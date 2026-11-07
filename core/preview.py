from django.conf import settings
from django.http import JsonResponse


class PreviewPaymentsMiddleware:
    paused_routes = {
        "add_bank_account",
        "get_data_plans",
        "initiate_cable_payment",
        "initiate_education_payment",
        "initiate_electricity_payment",
        "wallet_withdraw",
    }
    buyer_routes = {"initiate_service_payment", "wallet_fund_init"}
    settlement_routes = {"paystack_webhook", "verify_service_payment", "verify_wallet_funding"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        route = request.resolver_match.url_name
        payment_enabled = getattr(settings, "BETA_PAYMENTS_ENABLED", False)
        if route in self.buyer_routes and payment_enabled:
            if request.user.is_authenticated and request.user.email.casefold() in settings.BETA_BUYER_EMAILS:
                return None
            return JsonResponse(
                {"status": False, "message": "Payments are available to invited Payvict testers."},
                status=403,
            )
        if route in self.paused_routes or (
            not payment_enabled and route in self.buyer_routes | self.settlement_routes
        ):
            return JsonResponse(
                {"status": False, "message": "Payments are paused on the Payvict preview."},
                status=503,
            )
