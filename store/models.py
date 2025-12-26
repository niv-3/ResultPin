from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
from decimal import Decimal

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
    vendor_product_id = models.CharField(max_length=50)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    # NEW FIELD - Add this for Check Result button
    result_checker_url = models.URLField(
        max_length=300,
        blank=True,
        null=True,
        verbose_name="Result Checker URL",
        help_text="Official link to check results (e.g., WAEC, NECO, JAMB). Leave blank if not applicable."
    )

    def __str__(self):
        return self.name


class Transaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    vendor_used = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True)
    pin_serial = models.TextField(blank=True)  # Changed from CharField(50)
    pin_token = models.TextField(blank=True)   # Changed from CharField(30)
    quantity = models.PositiveIntegerField(default=1)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    profit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, blank=True)
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

class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    image = models.ImageField(upload_to='blog/', blank=True, null=True)
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
        ordering = ['id']

    def __str__(self):
        return self.question

# models.py
class ServiceCategory(models.Model):
    name = models.CharField(max_length=50)  # Airtime, Data, TV, Electricity
    slug = models.SlugField(unique=True)
    icon = models.ImageField(upload_to='services/icons/')
    short_description = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name


class ServiceProvider(models.Model):
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, related_name='providers')
    name = models.CharField(max_length=50)
    logo = models.ImageField(upload_to='services/providers/')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.name} ({self.category.name})"



from decimal import Decimal

class ServicePlan(models.Model):
    provider = models.ForeignKey(
        ServiceProvider,
        on_delete=models.CASCADE,
        related_name="plans"
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, blank=True)

    buy_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        null=True,
        blank=True
    )

    sell_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        null=True,
        blank=True
    )

    discount_percent = models.PositiveIntegerField(
        default=0,
        blank=True
    )

    description = models.CharField(max_length=255, blank=True)
    validity = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["provider__order", "sell_price"]  # temporarily remove "sell_price" if it causes error

    def __str__(self):
        return f"{self.provider.name} – {self.name}"

class HeroBanner(models.Model):
    PAGE_CHOICES = (
        ('home', 'Home'),
        ('airtime', 'Airtime'),
        ('data', 'Data'),
        ('exams', 'Exams'),
    )

    title = models.CharField(max_length=200)
    subtitle = models.TextField()
    cta_text = models.CharField(max_length=100, default="Buy Now")
    cta_link = models.CharField(max_length=200, default="#home")
    background_image = models.ImageField(upload_to="hero_banners/")
    is_active = models.BooleanField(default=True)
    page = models.CharField(
        max_length=50,
        choices=PAGE_CHOICES,
        default='home'
    )

    def __str__(self):
        return f"{self.title} ({self.page})"