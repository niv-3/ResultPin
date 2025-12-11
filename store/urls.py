# store/urls.py — FINAL 100% WORKING VERSION (NO MORE ERRORS)

from django.urls import path
from . import views

urlpatterns = [
    # Main
    path('', views.home, name='home'),
    path('initiate-payment/<int:product_id>/', views.initiate_payment, name='initiate_payment'),
    path('payment-success/', views.payment_success, name='payment_success'),

    # PROFESSIONAL PHONE OTP AUTH — ONLY THESE
    path('register/', views.register, name='register'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
]