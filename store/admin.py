from django.contrib import admin
from .models import (
    # =========================
    # CORE
    # =========================
    User,
    Vendor,
    Product,

    # =========================
    # TRANSACTIONS (SEPARATED)
    # =========================
    ExamTransaction,
    AirtimeTransaction,
    ServiceTransaction,

    # =========================
    # WALLET / REFERRAL
    # =========================
    WalletTransaction,
    Referral,

    # =========================
    # SERVICES
    # =========================
    ServiceCategory,
    ServiceProvider,
    ServicePlan,

    # =========================
    # CONTENT
    # =========================
    BlogPost,
    HeroBanner,
    FAQ,
    Review,
)


# ==================================================
# PRODUCT ADMIN
# ==================================================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sell_price", "buy_price", "is_active")
    list_editable = ("sell_price", "buy_price", "is_active")
    search_fields = ("name",)
    list_filter = ("is_active",)
    ordering = ("name",)


# ==================================================
# VENDOR ADMIN
# ==================================================
@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "api_url", "is_active", "priority")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("priority",)


# ==================================================
# EXAM TRANSACTIONS
# ==================================================
@admin.register(ExamTransaction)
class ExamTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "user",
        "product",
        "amount_paid",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("reference", "user__email", "user__phone")
    readonly_fields = ("reference", "created_at")
    ordering = ("-created_at",)


# ==================================================
# AIRTIME TRANSACTIONS
# ==================================================
@admin.register(AirtimeTransaction)
class AirtimeTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "user",
        "phone",
        "amount_paid",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("reference", "phone", "user__email")
    readonly_fields = ("reference", "created_at")
    ordering = ("-created_at",)


# ==================================================
# SERVICE TRANSACTIONS (DATA / TV / ELECTRICITY)
# ==================================================
@admin.register(ServiceTransaction)
class ServiceTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "user",
        "service_type",
        "amount_paid",
        "status",
        "created_at",
    )
    list_filter = ("service_type", "status", "created_at")
    search_fields = ("reference", "user__email")
    readonly_fields = ("reference", "created_at")
    ordering = ("-created_at",)


# ==================================================
# USER ADMIN
# ==================================================
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "phone", "is_active", "date_joined")
    search_fields = ("email", "phone", "username")
    list_filter = ("is_active",)
    ordering = ("-date_joined",)


# ==================================================
# WALLET TRANSACTIONS
# ==================================================
@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "transaction_type", "created_at")
    list_filter = ("transaction_type",)
    search_fields = ("user__email",)
    ordering = ("-created_at",)


# ==================================================
# REFERRALS
# ==================================================
@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("referrer", "referred", "amount_earned", "paid", "created_at")
    search_fields = ("referrer__email", "referred__email")
    list_filter = ("paid",)
    ordering = ("-created_at",)


# ==================================================
# BLOG POSTS
# ==================================================
@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "created_at", "published")
    list_filter = ("published", "created_at")
    search_fields = ("title", "content")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("-created_at",)


# ==================================================
# HERO BANNERS
# ==================================================
@admin.register(HeroBanner)
class HeroBannerAdmin(admin.ModelAdmin):
    list_display = ("title", "page", "is_active")
    list_editable = ("is_active",)
    search_fields = ("title",)


# ==================================================
# SERVICE CATEGORY
# ==================================================
@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "order")
    list_editable = ("is_active", "order")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)
    ordering = ("order",)


# ==================================================
# SERVICE PROVIDER
# ==================================================
@admin.register(ServiceProvider)
class ServiceProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active", "order")
    list_filter = ("category", "is_active")
    list_editable = ("is_active", "order")
    search_fields = ("name",)
    ordering = ("order",)


# ==================================================
# SERVICE PLANS
# ==================================================
@admin.register(ServicePlan)
class ServicePlanAdmin(admin.ModelAdmin):
    list_display = ("provider", "name", "discount_percent", "is_active")
    list_filter = ("provider", "is_active")
    search_fields = ("name", "code", "provider__name")


# ==================================================
# FAQ
# ==================================================
@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("question", "is_active")
    list_editable = ("is_active",)
    search_fields = ("question",)


# ==================================================
# REVIEW
# ==================================================
@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("name", "rating", "created_at")
    search_fields = ("name", "comment")
    ordering = ("-created_at",)
