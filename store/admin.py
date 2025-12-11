# store/admin.py
from django.contrib import admin
from .models import Product, Vendor, Transaction, User, WalletTransaction, Referral

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sell_price', 'buy_price', 'is_active')
    list_editable = ('sell_price', 'buy_price', 'is_active')

@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'priority')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('reference', 'product', 'amount_paid', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('reference',)

admin.site.register(User)
admin.site.register(WalletTransaction)
admin.site.register(Referral)