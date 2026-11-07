from django.http import JsonResponse


class PreviewPaymentsMiddleware:
    blocked_routes = {
        "add_bank_account",
        "get_data_plans",
        "initiate_cable_payment",
        "initiate_education_payment",
        "initiate_electricity_payment",
        "initiate_service_payment",
        "paystack_webhook",
        "verify_service_payment",
        "verify_wallet_funding",
        "wallet_fund_init",
        "wallet_withdraw",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.resolver_match.url_name in self.blocked_routes:
            return JsonResponse(
                {"status": False, "message": "Payments are paused on the KoboTap preview."},
                status=503,
            )
