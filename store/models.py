from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
import uuid
from decimal import Decimal
from django.conf import settings


# =========================
# USER
# =========================
class User(AbstractUser):
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    referral_code = models.CharField(max_length=10, unique=True, blank=True, null=True)
    referred_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="referrals"
    )

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = str(uuid.uuid4())[:8].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username


# =========================
# VENDOR / EXAM PRODUCTS
# =========================
class Vendor(models.Model):
    name = models.CharField(max_length=50)
    api_url = models.URLField()
    api_key = models.CharField(max_length=200)
    api_secret = models.CharField(max_length=200, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=1)

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=50)
    vendor_product_id = models.CharField(max_length=50)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to="products/", blank=True, null=True)
    is_active = models.BooleanField(default=True)

    result_checker_url = models.URLField(
        max_length=300,
        blank=True,
        null=True,
        help_text="Official link to check results"
    )

    def __str__(self):
        return self.name


# =========================
# SERVICES (Airtime, Data, TV, Electricity)
# =========================
class ServiceCategory(models.Model):
    name = models.CharField(max_length=50)
    slug = models.SlugField(unique=True)
    icon = models.ImageField(upload_to="services/icons/")
    short_description = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.name


class ServiceProvider(models.Model):
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.CASCADE,
        related_name="providers"
    )
    name = models.CharField(max_length=50)
    logo = models.ImageField(upload_to="services/providers/")
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

    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    market_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)

    description = models.CharField(max_length=255, blank=True)
    validity = models.CharField(max_length=50, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def profit_amount(self):
        return self.selling_price - self.cost_price

    @property
    def discount_amount(self):
        return self.market_price - self.selling_price

# =========================
# BASE TRANSACTION (ABSTRACT)
# =========================
class BaseTransaction(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    reference = models.CharField(max_length=100, unique=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    payment_method = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


# =========================
# EXAM TRANSACTIONS
# =========================
class ExamTransaction(BaseTransaction):
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    profit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    pin_token = models.CharField(max_length=255, blank=True, null=True)
    pin_serial = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Exam {self.reference}"


# =========================
# AIRTIME TRANSACTIONS
# =========================
class AirtimeTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    phone = models.CharField(max_length=20)

    service_plan = models.ForeignKey(
        ServicePlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)

    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, default="pending")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Airtime {self.phone} – {self.reference}"



# =========================
# OTHER SERVICE TRANSACTIONS
# =========================
class ServiceTransaction(BaseTransaction):
    SERVICE_TYPES = (
        ("data", "Data"),
        ("tv", "TV"),
        ("electricity", "Electricity"),
    )

    service_type = models.CharField(max_length=20, choices=SERVICE_TYPES)

    plan = models.ForeignKey(
        ServicePlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    identifier = models.CharField(
        max_length=50,
        help_text="Meter number, decoder number, etc"
    )

    def __str__(self):
        return f"{self.service_type} ({self.reference})"


# =========================
# WALLET / REFERRALS
# =========================
class Referral(models.Model):
    referrer = models.ForeignKey(User, related_name="given_referrals", on_delete=models.CASCADE)
    referred = models.ForeignKey(User, related_name="received_referrals", on_delete=models.CASCADE)
    amount_earned = models.DecimalField(max_digits=10, decimal_places=2, default=150.00)
    paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class WalletTransaction(models.Model):
    TRANSACTION_TYPES = (
        ("credit", "Credit"),
        ("debit", "Debit"),
    )

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    )

    DESCRIPTION_CHOICES = (
        ("Wallet Funding", "Wallet Funding"),
        ("Service Purchase", "Service Purchase"),
        ("Savings from Discount", "Savings from Discount"),
        ("Refund for failed purchase", "Refund for failed purchase"),
        ("Bank Withdrawal", "Bank Withdrawal"),
        ("Referral Bonus", "Referral Bonus"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet_transactions"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    description = models.CharField(max_length=255, choices=DESCRIPTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} | {self.transaction_type} | ₦{self.amount}"

# =========================
# BANK ACCOUNT (NEW FOR WITHDRAWALS)
# =========================
class BankAccount(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bank_code = models.CharField(max_length=10)  # Paystack bank code
    account_number = models.CharField(max_length=20)
    account_name = models.CharField(max_length=100)
    recipient_code = models.CharField(max_length=100, blank=True)  # Paystack recipient code (create on save)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.account_name} - {self.account_number}"

    def save(self, *args, **kwargs):
        if not self.recipient_code:
            # Create Paystack recipient (implement in views or signal)
            pass
        super().save(*args, **kwargs)


# =========================
# BLOG / REVIEWS / FAQ
# =========================
class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    image = models.ImageField(upload_to="blog/", blank=True, null=True)
    content = models.TextField()
    author = models.CharField(max_length=100, default="ResultPin Team")
    created_at = models.DateTimeField(auto_now_add=True)
    read_time = models.CharField(max_length=20, default="5 min read")
    published = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("blog_detail", kwargs={"slug": self.slug})


class Review(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    location = models.CharField(max_length=100, blank=True)
    rating = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.rating}⭐)"


class FAQ(models.Model):
    question = models.CharField(max_length=200)
    answer = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.question


# =========================
# HERO BANNERS
# =========================
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
    background_image = models.ImageField(upload_to="hero_banners/")
    is_active = models.BooleanField(default=True)
    page = models.CharField(max_length=50, choices=PAGE_CHOICES, default="home")

    def __str__(self):
        return f"{self.title} ({self.page})"