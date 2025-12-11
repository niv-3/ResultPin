from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid

class User(AbstractUser):
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    referral_code = models.CharField(max_length=10, unique=True, blank=True, null=True)
    referred_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='referrals')

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = str(uuid.uuid4())[:8].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username

class Vendor(models.Model):
    name = models.CharField(max_length=50)
    api_url = models.URLField()
    api_key = models.CharField(max_length=200)
    api_secret = models.CharField(max_length=200, blank=True, null=True)  # For VTpass password
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=1)  # Lower = higher priority

    def __str__(self):
        return self.name

class Product(models.Model):
    name = models.CharField(max_length=50)
    vendor_product_id = models.CharField(max_length=50)  # e.g., 'waecdirect' for epins
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Transaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    vendor_used = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True)
    pin_serial = models.CharField(max_length=50, blank=True)
    pin_token = models.CharField(max_length=30, blank=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    profit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, blank=True)  # 'opay', 'card', etc.
    status = models.CharField(max_length=20, default='pending')
    reference = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Referral(models.Model):
    referrer = models.ForeignKey(User, related_name='given_referrals', on_delete=models.CASCADE)
    referred = models.ForeignKey(User, related_name='received_referrals', on_delete=models.CASCADE)
    amount_earned = models.DecimalField(max_digits=10, decimal_places=2, default=150.00)
    paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class WalletTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=10)  # 'credit' or 'debit'
    description = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)