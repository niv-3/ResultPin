# store/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.admin.forms import AdminAuthenticationForm
from django import forms
from .models import *
from .supplier_pricing import estimated_data_margin


class AdminEmailLoginForm(AdminAuthenticationForm):
    username = forms.CharField(
        label="Admin username or email",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )


admin.site.login_form = AdminEmailLoginForm


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "phone",
        "wallet_balance",
        "is_staff",
        "is_active",
        "date_joined",
    )
    search_fields = ("username", "email", "phone")
    fieldsets = BaseUserAdmin.fieldsets + (("Phone sign-in", {"fields": ("phone",)}),)
    ordering = ("-date_joined",)
    

@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}



@admin.register(DataSupplier)
class DataSupplierAdmin(admin.ModelAdmin):
    list_display = ("vendor", "adapter", "enabled", "funded", "funding_fee_rate", "purchase_fee", "paused_until")
    list_filter = ("enabled", "funded", "adapter")


admin.site.register(Vendor)
admin.site.register(Product)
admin.site.register(WalletTransaction)
admin.site.register(Referral)
admin.site.register(ServiceProvider)
admin.site.register(ServicePlan)
admin.site.register(ExamTransaction)
@admin.register(AirtimeTransaction)
class AirtimeTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "service_plan", "amount_paid", "status", "supplier_vendor", "supplier_cost", "supplier_total_cost", "cashback_snapshot", "created_at")
    list_filter = ("status", "supplier_adapter", "payment_method")
    search_fields = ("reference", "supplier_reference")
    readonly_fields = ("supplier_vendor", "supplier_adapter", "supplier_external_id", "supplier_network_code", "supplier_cost", "supplier_total_cost", "cashback_snapshot")

admin.site.register(ServiceTransaction)
admin.site.register(BlogPost)
admin.site.register(HeroBanner)
admin.site.register(FAQ)
admin.site.register(Review)


@admin.register(SupplierQuote)
class SupplierQuoteAdmin(admin.ModelAdmin):
    list_display = ("plan", "vendor", "external_id", "network_code", "cost", "estimated_margin", "estimated_card_margin", "available", "approved", "checked_at")
    list_filter = ("vendor", "available", "approved")
    list_select_related = ("plan", "vendor")
    search_fields = ("plan__name", "external_id", "label")

    def supplier_total(self, quote):
        if hasattr(quote.vendor, "data_supplier"):
            from .data_routing import total_supplier_cost
            return total_supplier_cost(quote)
        return None

    @admin.display(description="Est. wallet margin")
    def estimated_margin(self, quote):
        return estimated_data_margin(quote.plan, quote.cost, supplier_total=self.supplier_total(quote))


    @admin.display(description="Est. card margin")
    def estimated_card_margin(self, quote):
        return estimated_data_margin(quote.plan, quote.cost, payment_method="card", supplier_total=self.supplier_total(quote))
