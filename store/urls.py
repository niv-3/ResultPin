from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    # ======================
    # MAIN
    # ======================
    path('', views.home, name='home'),
    path('initiate-payment/<int:product_id>/', views.initiate_payment, name='initiate_payment'),
    path('payment-success/', views.payment_success, name='payment_success'),

    # ======================
    # REVIEW FLOW
    # ======================
    path('submit-review/', views.submit_review, name='submit_review'),
    path('review-thank-you/', views.review_thank_you, name='review_thank_you'),

    # ======================
    # AUTH
    # ======================
    path('register/', views.register, name='register'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),

    # ======================
    # PASSWORD RESET
    # ======================
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='store/auth/password_reset.html'
        ),
        name='password_reset'
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='store/auth/password_reset_done.html'
        ),
        name='password_reset_done'
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='store/auth/password_reset_confirm.html'
        ),
        name='password_reset_confirm'
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='store/auth/password_reset_complete.html'
        ),
        name='password_reset_complete'
    ),

    # ======================
    # BLOG
    # ======================
    path('blog/', views.blog_list, name='blog_list'),
    path('blog/<slug:slug>/', views.blog_detail, name='blog_detail'),
    # urls.py
    path('services/<slug:slug>/', views.service_detail, name='service_detail'),

]
