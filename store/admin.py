from django.contrib import admin
from .models import (
    Product,
    Vendor,
    Transaction,
    User,
    WalletTransaction,
    Referral
)


# ==============================
# PRODUCT ADMIN
# ==============================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sell_price', 'buy_price', 'is_active')
    list_editable = ('sell_price', 'buy_price', 'is_active')
    search_fields = ('name',)
    list_filter = ('is_active',)


# ==============================
# VENDOR ADMIN
# ==============================
@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_url', 'is_active', 'priority')
    list_filter = ('is_active',)
    search_fields = ('name',)


# ==============================
# TRANSACTION ADMIN (VERY IMPORTANT)
# ==============================
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'reference',
        'product',
        'amount_paid',
        'status',
        'payment_method',
        'created_at',
    )

    list_filter = (
        'status',
        'payment_method',
        'created_at',
    )

    search_fields = (
        'reference',
        'pin_token',
        'user__email',
        'user__phone',
    )

    # 🔒 PROTECT CRITICAL FIELDS
    readonly_fields = (
        'reference',
        'user',
        'product',
        'amount_paid',
        'profit',
        'payment_method',
        'pin_token',
        'pin_serial',
        'created_at',
    )

    fieldsets = (
        ('Transaction Info', {
            'fields': (
                'reference',
                'user',
                'product',
                'status',
                'payment_method',
            )
        }),
        ('Financials', {
            'fields': (
                'amount_paid',
                'profit',
            )
        }),
        ('PIN Details (Read-Only)', {
            'fields': (
                'pin_token',
                'pin_serial',
            )
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
            )
        }),
    )


# ==============================
# USER ADMIN
# ==============================
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'phone', 'is_active', 'date_joined')
    search_fields = ('email', 'phone')
    list_filter = ('is_active',)


# ==============================
# WALLET TRANSACTIONS
# ==============================
@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'transaction_type', 'created_at')
    list_filter = ('transaction_type',)
    search_fields = ('user__email',)


# ==============================
# REFERRALS
# ==============================
@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    # Use correct field name from your model
    list_display = ('referrer', 'get_referred_user', 'created_at')
    search_fields = ('referrer__email', 'user__email')

    def get_referred_user(self, obj):
        return obj.user  # Replace 'user' if your model uses a different field
    get_referred_user.short_description = "Referred User"
