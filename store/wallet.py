from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from store.models import WalletTransaction, User

def debit_wallet(user, amount, description):
    amount = Decimal(amount)

    if user.balance < amount:
        raise ValidationError("Insufficient wallet balance")

    with transaction.atomic():
        user.balance -= amount
        user.save(update_fields=["balance"])

        WalletTransaction.objects.create(
            user=user,
            amount=amount,
            transaction_type="debit",
            description=description
        )


def credit_wallet(user, amount, description):
    amount = Decimal(amount)

    with transaction.atomic():
        user.balance += amount
        user.save(update_fields=["balance"])

        WalletTransaction.objects.create(
            user=user,
            amount=amount,
            transaction_type="credit",
            description=description
        )
