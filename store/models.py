# store/models.py

from decimal import Decimal
from uuid import uuid4

from django.db import models
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AbstractUser


# ==================================================
# CUSTOM USER
# ==================================================
class User(AbstractUser):
    """
    Custom User model.
    Wallet balance is derived from ledger (never stored).
    """

    @property
    def wallet_balance(self):
        credits = self.wallet_transactions.filter(
            transaction_type="credit",
            status="success"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        debits = self.wallet_transactions.filter(
            transaction_type="debit",
            status="success"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        return credits - debits

    def debit_wallet(self, amount, source="", reference=None):
        if self.wallet_balance < amount:
            raise ValidationError("Insufficient funds")

        return WalletTransaction.objects.create(
            user=self,
            amount=amount,
            transaction_type="debit",
            source=source,
            status="success",
            reference=reference or str(uuid4()),
        )

    def credit_wallet(self, amount, source="", reference=None):
        return WalletTransaction.objects.create(
            user=self,
            amount=amount,
            transaction_type="credit",
            source=source,
            status="success",
            reference=reference or str(uuid4()),
        )

    # ✅ MUST BE INSIDE THE CLASS
    @property
    def total_referrals(self):
        return self.referrals_made.count()

# ==================================================
# VENDOR
# ==================================================
class Vendor(models.Model):
    name = models.CharField(max_length=100)
    api_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        return self.name


# ==================================================
# PRODUCT
# ==================================================
class Product(models.Model):
    name = models.CharField(max_length=50)
    vendor_product_id = models.CharField(max_length=50)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to="products/", blank=True, null=True)
    is_active = models.BooleanField(default=True)

    result_checker_url = models.URLField(
        max_length=300, blank=True, null=True
    )

    def __str__(self):
        return self.name


# ==================================================
# WALLET TRANSACTION (LEDGER)
# ==================================================
class WalletTransaction(models.Model):
    TRANSACTION_TYPE_CHOICES = (
        ("credit", "Credit"),
        ("debit", "Debit"),
    )

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    )

    user = models.ForeignKey(
        User,
        related_name="wallet_transactions",
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    source = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    reference = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "transaction_type"]),
            models.Index(fields=["reference"]),
        ]

    def clean(self):
        if (
            self.transaction_type == "debit"
            and self.status == "success"
            and self.pk is None
        ):
            if self.user.wallet_balance < self.amount:
                raise ValidationError("Insufficient funds")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.reference


# ==================================================
# REFERRALS
# ==================================================
class Referral(models.Model):
    referrer = models.ForeignKey(
        User, related_name="referrals_made", on_delete=models.CASCADE
    )
    referred = models.ForeignKey(
        User, related_name="referred_by", on_delete=models.CASCADE
    )
    amount_earned = models.DecimalField(max_digits=10, decimal_places=2)
    paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


# ==================================================
# SERVICE CATALOG
# ==================================================
from django.utils.text import slugify

class ServiceCategory(models.Model):
    name = models.CharField(max_length=50)
    slug = models.SlugField(unique=True, blank=True)
    icon = models.ImageField(upload_to="services/icons/", null=True, blank=True)
    short_description = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name



class ServiceProvider(models.Model):
    category = models.ForeignKey(
        ServiceCategory, related_name="providers", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=50)
    logo = models.ImageField(upload_to="services/providers/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.name} ({self.category.name})"


class ServicePlan(models.Model):
    provider = models.ForeignKey(
        ServiceProvider,
        on_delete=models.CASCADE,
        related_name="plans"
    )

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)

    # ---- PRICING (LOCKED SOURCE OF TRUTH) ----
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    market_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    selling_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    # ---- BUSINESS FLAGS ----
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ---- CONSTANT REWARD RATE (OPAY STYLE) ----
    REWARD_RATE = Decimal("0.015")  # 1.5%

    # -----------------------------
    # PROFIT (INTERNAL ONLY)
    # -----------------------------
    @property
    def profit_amount(self):
        if self.cost_price is None or self.selling_price is None:
            return None
        return self.selling_price - self.cost_price

    # -----------------------------
    # CUSTOMER REWARD (LOCKED)
    # -----------------------------
    @property
    def reward_amount(self):
        """
        Opay-style:
        Reward is calculated ONLY from selling price,
        not from profit, not from market price.
        """
        if self.selling_price is None:
            return None
        return (self.selling_price * self.REWARD_RATE).quantize(Decimal("0.01"))

    # -----------------------------
    # DISCOUNT FOR CUSTOMERS (DISPLAY ONLY)
    # -----------------------------
    @property
    def discount_amount(self):
        if self.market_price and self.selling_price:
            return (self.market_price - self.selling_price).quantize(Decimal("0.01"))
        return Decimal("0.00")

    # -----------------------------
    # VALIDATION (ANTI-LOSS GUARD)
    # -----------------------------
    def clean(self):
        if (
            self.cost_price is not None and
            self.selling_price is not None and
            self.selling_price < self.cost_price
        ):
            raise ValidationError(
                "Selling price cannot be below cost price."
            )

    def __str__(self):
        return self.name


# ==================================================
# BUSINESS TRANSACTIONS
# ==================================================
class ExamTransaction(models.Model):
    reference = models.CharField(max_length=100, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Exam {self.reference}"


class AirtimeTransaction(models.Model):
    PAYMENT_CHOICES = (
        ("wallet", "Wallet"),
        ("card", "Card"),
    )

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_CHOICES, default="card"
    )
    phone = models.CharField(max_length=20)
    service_plan = models.ForeignKey(
        ServicePlan, on_delete=models.SET_NULL, null=True, blank=True
    )
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Airtime {self.phone} – {self.reference}"


class ServiceTransaction(models.Model):
    reference = models.CharField(max_length=100, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    service_type = models.CharField(max_length=50)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)


# ==================================================
# CONTENT
# ==================================================
class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class HeroBanner(models.Model):
    PAGE_CHOICES = (
        ("home", "Home"),
        ("airtime", "Airtime"),
        ("data", "Data"),
        ("exams", "Exams"),
    )

    title = models.CharField(max_length=200)
    subtitle = models.TextField()
    cta_text = models.CharField(max_length=100, default="Buy Now")
    cta_link = models.CharField(max_length=200, default="#home")
    background_image = models.ImageField(
        upload_to="hero_banners/", null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    page = models.CharField(max_length=50, choices=PAGE_CHOICES, default="home")

    def __str__(self):
        return f"{self.title} ({self.page})"


class FAQ(models.Model):
    question = models.CharField(max_length=255)
    answer = models.TextField()
    is_active = models.BooleanField(default=True)


class Review(models.Model):
    name = models.CharField(max_length=100)
    rating = models.PositiveIntegerField()
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


# ==================================================
# BANK ACCOUNT (NO WITHDRAWAL YET)
# ==================================================
class BankAccount(models.Model):
    user = models.ForeignKey(
        User, related_name="bank_accounts", on_delete=models.CASCADE
    )
    account_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=20)
    bank_name = models.CharField(max_length=100)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.bank_name} - {self.account_number}"
