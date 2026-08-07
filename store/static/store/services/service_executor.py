from decimal import Decimal
from django.db import transaction
from ..models import AirtimeTransaction


def execute_service_purchase(*, user, plan, phone, service_type, amount_naira, payment_method, reference):
    """
    Single execution layer for ALL services:
    airtime, data, cable, electricity (future-proof)
    """

    with transaction.atomic():

        txn = AirtimeTransaction.objects.create(
            user=user,
            service_plan=plan,
            phone=phone,
            amount_paid=amount_naira,
            payment_method=payment_method,
            reference=reference,
            status="pending"
        )

        # =========================
        # AIRTIME
        # =========================
        if service_type == "airtime":

            if not plan.vendor_provider_id:
                raise ValueError(f"Airtime plan missing vendor_provider_id")

            api_response = plan.provider.purchase_airtime(
                provider_id=plan.vendor_provider_id,
                phone=phone,
                amount=amount_naira
            )

        # =========================
        # DATA
        # =========================
        elif service_type == "data":

            if not plan.vendor_bundle_id:
                raise ValueError("Data plan missing vendor_bundle_id")

            api_response = plan.provider.purchase_data(
                bundle_id=plan.vendor_bundle_id,
                phone=phone,
                bundle_name=plan.name
            )

        # =========================
        # FUTURE EXTENSIONS
        # =========================
        else:
            raise ValueError(f"Unsupported service type: {service_type}")

        return txn, api_response