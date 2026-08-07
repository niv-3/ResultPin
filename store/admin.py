# store/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import *


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "wallet_balance",
        "is_staff",
        "is_active",
        "date_joined",
    )
    search_fields = ("username", "email")
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
