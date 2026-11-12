# store/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.admin.forms import AdminAuthenticationForm
from django import forms
from .models import *
from .supplier_pricing import estimated_data_margin


class AdminEmailLoginForm(AdminAuthenticationForm):
    username = forms.EmailField(label="Admin email", widget=forms.EmailInput(attrs={"autofocus": True}))


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



admin.site.register(Vendor)
admin.site.register(Product)
admin.site.register(WalletTransaction)
admin.site.register(Referral)
admin.site.register(ServiceProvider)
admin.site.register(ServicePlan)
admin.site.register(ExamTransaction)
admin.site.register(AirtimeTransaction)
admin.site.register(ServiceTransaction)
admin.site.register(BlogPost)
admin.site.register(HeroBanner)
admin.site.register(FAQ)
admin.site.register(Review)


@admin.register(SupplierQuote)
class SupplierQuoteAdmin(admin.ModelAdmin):
    list_display = ("plan", "vendor", "external_id", "cost", "estimated_margin", "estimated_card_margin", "available", "approved", "checked_at")
    list_filter = ("vendor", "available", "approved")
    list_select_related = ("plan", "vendor")
    search_fields = ("plan__name", "external_id", "label")

    @admin.display(description="Est. wallet margin")
    def estimated_margin(self, quote):
        return estimated_data_margin(quote.plan, quote.cost)


    @admin.display(description="Est. card margin")
    def estimated_card_margin(self, quote):
        return estimated_data_margin(quote.plan, quote.cost, payment_method="card")
