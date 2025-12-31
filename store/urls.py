# store/urls.py

from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    # ======================
    # MAIN
    # ======================
    path("", views.home, name="home"),
    path("wallet/", views.wallet, name="wallet"),
    
        
    path("wallet/fund/", views.wallet_fund, name="wallet_fund"),
    path("wallet/fund/init/", views.wallet_fund_init, name="wallet_fund_init"),
    path("verify-wallet-funding/", views.verify_wallet_funding, name="verify_wallet_funding"),
    path("wallet/withdraw/", views.wallet_withdraw, name="wallet_withdraw"),
    path("wallet/add-bank/", views.add_bank_account, name="add_bank_account"),

    # ======================
    # SERVICES
    # ======================
    path(
        "services/<slug:slug>/",
        views.service_dashboard,
        name="service_dashboard"
    ),

    # ======================
    # PAYMENTS (UNIFIED FOR ALL SERVICES)
    # ======================
    path(
        "initiate-service-payment/<int:plan_id>/",
        views.initiate_service_payment,
        name="initiate_service_payment"
    ),
    path(
        "verify-service-payment/",
        views.verify_service_payment,
        name="verify_service_payment"
    ),
    path(
        "payment-success/",
        views.payment_success,
        name="payment_success"
    ),

    # ======================
    # AUTH
    # ======================
    path("register/", views.register, name="register"),
    path("login/", views.custom_login, name="login"),
    path("logout/", views.custom_logout, name="logout"),
    path("verify-otp/", views.verify_otp, name="verify_otp"),
    path("resend-otp/", views.resend_otp, name="resend_otp"),

    # ======================
    # PASSWORD RESET
    # ======================
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(template_name="store/auth/password_reset.html"),
        name="password_reset"
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="store/auth/password_reset_done.html"),
        name="password_reset_done"
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(template_name="store/auth/password_reset_confirm.html"),
        name="password_reset_confirm"
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(template_name="store/auth/password_reset_complete.html"),
        name="password_reset_complete"
    ),

    # ======================
    # BLOG
    # ======================
    path("blog/", views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),

    # ======================
    # REVIEWS
    # ======================
    path("submit-review/", views.submit_review, name="submit_review"),
    path("review-thank-you/", views.review_thank_you, name="review_thank_you"),
]