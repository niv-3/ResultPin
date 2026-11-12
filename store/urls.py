from django.urls import path
from django.contrib.auth import views as auth_views
from . import bills, google_auth, views
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
    path("services/tv/", bills.dashboard, {"kind": "cable"}, name="tv_dashboard"),
    path("services/cable-tv/", bills.dashboard, {"kind": "cable"}),
    path("services/cable/", bills.dashboard, {"kind": "cable"}),
    path("services/dstv/", bills.dashboard, {"kind": "cable"}),
    path("services/electricity/", bills.dashboard, {"kind": "electricity"}, name="electricity_dashboard"),

    path("services/education/", bills.dashboard, {"kind": "education"}, name="education_dashboard"),

    path("services/<slug:slug>/checkout/<int:plan_id>/", views.service_checkout, name="service_checkout"),

    # GENERIC SERVICE PAGES (airtime, data, etc.) — AFTER specific ones
    path(
        "services/<slug:slug>/",
        views.service_dashboard,
        name="service_dashboard",
    ),

    # Payment initiation - SERVICE-SPECIFIC (this fixes the issue)
    path("service/pay/cable/", bills.purchase, {"kind": "cable"}, name="initiate_cable_payment"),
    path("service/pay/electricity/", bills.purchase, {"kind": "electricity"}, name="initiate_electricity_payment"),
    path("service/pay/education/", bills.purchase, {"kind": "education"}, name="initiate_education_payment"),
    path("bills/<str:kind>/<str:reference>/", bills.receipt, name="bill_receipt"),
    path("service/pay/<slug:category_slug>/<int:plan_id>/", views.initiate_service_payment, name="initiate_service_payment"),
    
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
    path("auth/google/", google_auth.start, name="google_signin"),
    path("auth/google/callback/", google_auth.callback, name="google_callback"),
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
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("blog/", views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),

    # ======================
    # REVIEWS
    # ======================
    path("review/submit/", views.submit_review, name="submit_review"),
    path("review/thank-you/", views.review_thank_you, name="review_thank_you"),
    path('faq/', views.faq_view, name='faq_page'),
]
