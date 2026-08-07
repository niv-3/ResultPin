from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views import paystack_webhook

urlpatterns = [
    # ======================
    # MAIN
    # ======================
    path("", views.home, name="home"),
    path("wallet/", views.wallet, name="wallet"),

    # ======================
    # WALLET
    # ======================
    path("wallet/fund/", views.wallet_fund, name="wallet_fund"),
    path("wallet/fund/init/", views.wallet_fund_init, name="wallet_fund_init"),
    path("wallet/fund/verify/", views.verify_wallet_funding, name="verify_wallet_funding"),
    path("wallet/withdraw/", views.wallet_withdraw, name="wallet_withdraw"),
    path("wallet/bank/add/", views.add_bank_account, name="add_bank_account"),
    path("paystack_webhook/", paystack_webhook, name="paystack_webhook"),

    # ======================
    # SERVICES - Specific pages FIRST (order matters!)
    # ======================
    path("services/tv/", views.tv_dashboard, name="tv_dashboard"),
    path("services/electricity/", views.electricity_dashboard, name="electricity_dashboard"),

    # GENERIC SERVICE PAGES (airtime, data, etc.) — AFTER specific ones
    path(
        "services/<slug:slug>/",
        views.service_dashboard,
        name="service_dashboard",
    ),

    # Payment initiation - SERVICE-SPECIFIC (this fixes the issue)
    path("service/pay/<slug:category_slug>/<int:plan_id>/", views.initiate_service_payment, name="initiate_service_payment"),
    path("service/pay/cable/<int:plan_id>/", views.initiate_cable_payment, name="initiate_cable_payment"),
    path("service/pay/electricity/<int:plan_id>/", views.initiate_electricity_payment, name="initiate_electricity_payment"),
    
    #=========
    #debug url
    #==========

    path("debug/data-plans/", views.get_data_plans, name="get_data_plans"),

    # Payment callbacks
    path(
        "payment/success/",
        views.payment_success,
        name="payment_success",
    ),
    path("verify-service-payment/", views.verify_service_payment, name="verify_service_payment"),

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
        auth_views.PasswordResetView.as_view(
            template_name="store/auth/password_reset.html"
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="store/auth/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="store/auth/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="store/auth/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),

    # ======================
    # BLOG
    # ======================
    path("blog/", views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),

    # ======================
    # REVIEWS
    # ======================
    path("review/submit/", views.submit_review, name="submit_review"),
    path("review/thank-you/", views.review_thank_you, name="review_thank_you"),
    path('faq/', views.faq_view, name='faq_page'),
]
