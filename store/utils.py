import re


def normalize_phone(raw_phone: str) -> str | None:
    """
    Normalize Nigerian phone numbers to +234XXXXXXXXXX
    Returns None if invalid
    """
    if not raw_phone:
        return None

    digits = re.sub(r"\D", "", raw_phone)

    if digits.startswith("234") and len(digits) == 13:
        return "+234" + digits[3:]

    if digits.startswith("0") and len(digits) == 11:
        return "+234" + digits[1:]

    if len(digits) == 10:
        return "+234" + digits

    return None


def process_service_delivery(request, svc_txn, plan, phone) -> bool:
    """
    DELIVERY HANDLER
    Replace this later with real provider API.
    For now: safe stub that always succeeds.
    """

    # You can log for debugging
    print(
        f"[DELIVERY] {plan.name} → {phone} | Ref: {svc_txn.reference}"
    )

    return True
