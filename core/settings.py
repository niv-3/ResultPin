"""
Django settings for Payvict.
"""

from pathlib import Path
import os

import dj_database_url
from dotenv import load_dotenv


# =========================================================
# BASE DIRECTORY / ENVIRONMENT
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


# =========================================================
# SECURITY
# =========================================================

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-change-this-in-development"
)

DEBUG = os.getenv("DEBUG", "True").lower() == "true"


ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "ALLOWED_HOSTS",
        "127.0.0.1,localhost"
    ).split(",")
    if host.strip()
]


CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CSRF_TRUSTED_ORIGINS",
        (
            "http://127.0.0.1:8000,"
            "http://localhost:8000,"
            "https://*.ngrok-free.dev,"
            "https://*.ngrok.io"
        )
    ).split(",")
    if origin.strip()
]


# Secure cookies only outside local development
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG

CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"

# Required because current JavaScript reads the CSRF cookie
CSRF_COOKIE_HTTPONLY = False


# General security
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

# Keep disabled for now.
# We can enable these when the production domain is ready.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0

# Useful when deployed behind Render/ngrok/reverse proxies
SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)


# =========================================================
# APPLICATIONS
# =========================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    # Local app
    "store",

    # Third-party apps
    "rest_framework",
    "crispy_forms",
    "crispy_bootstrap5",
]


# =========================================================
# MIDDLEWARE
# =========================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.idle_sessions.IdleSessionMiddleware",
    "core.session_pages.SessionPageCacheMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# =========================================================
# URL / WSGI
# =========================================================

ROOT_URLCONF = "core.urls"

WSGI_APPLICATION = "core.wsgi.application"


# =========================================================
# TEMPLATES
# =========================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",

        "DIRS": [
            BASE_DIR / "store" / "templates",
        ],

        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "store.context_processors.navigation",
            ],
        },
    },
]


# =========================================================
# DATABASE
# =========================================================

DATABASES = {
    "default": dj_database_url.parse(
        os.getenv(
            "DATABASE_URL",
            f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
        ),
        conn_max_age=600,
    )
}


# =========================================================
# AUTHENTICATION / PASSWORDS
# =========================================================

AUTH_USER_MODEL = "store.User"
AUTHENTICATION_BACKENDS = ["store.authentication.EmailOrPhoneBackend"]


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        )
    },
]


LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/wallet/"
LOGOUT_REDIRECT_URL = "/"


# =========================================================
# INTERNATIONALIZATION
# =========================================================

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Africa/Lagos"

USE_I18N = True

USE_TZ = True


# =========================================================
# STATIC FILES
# =========================================================

STATIC_URL = "/static/"

STATIC_ROOT = BASE_DIR / "staticfiles"


STORAGES = {
    "default": {
        "BACKEND": (
            "django.core.files.storage.FileSystemStorage"
        ),
    },

    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage."
            "ManifestStaticFilesStorage"
        ),
    },
}


# =========================================================
# MEDIA FILES
# =========================================================

MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# =========================================================
# EMAIL
# =========================================================

EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
)

EMAIL_HOST = "smtp.gmail.com"

EMAIL_PORT = 587

EMAIL_USE_TLS = True

EMAIL_HOST_USER = os.getenv(
    "EMAIL_HOST_USER"
)

EMAIL_HOST_PASSWORD = os.getenv(
    "EMAIL_HOST_PASSWORD"
)

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    "Payvict <resultpin.solutions@gmail.com>"
)


# =========================================================
# PAYSTACK
# =========================================================

PAYSTACK_PUBLIC_KEY = os.getenv(
    "PAYSTACK_PUBLIC_KEY"
)

PAYSTACK_SECRET_KEY = os.getenv(
    "PAYSTACK_SECRET_KEY"
)


# =========================================================
# CHEAP DATA HUB
# =========================================================

CHEAPDATAHUB_API_KEY = os.getenv(
    "CHEAPDATAHUB_API_KEY"
)


# =========================================================
# DJANGO DEFAULTS
# =========================================================

DEFAULT_AUTO_FIELD = (
    "django.db.models.BigAutoField"
)


# =========================================================
# CRISPY FORMS
# =========================================================

CRISPY_ALLOWED_TEMPLATE_PACKS = (
    "bootstrap5"
)

CRISPY_TEMPLATE_PACK = (
    "bootstrap5"
)


# =========================================================
# SESSIONS
# =========================================================

SESSION_ENGINE = (
    "django.contrib.sessions.backends.db"
)

SESSION_SAVE_EVERY_REQUEST = False

SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Real user activity refreshes the session; passive background requests do not.
SESSION_IDLE_TIMEOUT = 15 * 60
# Anonymous verification/OAuth sessions need time to complete sign-in.
# Authenticated sessions receive the shorter idle expiry in the middleware.
SESSION_COOKIE_AGE = 3600
# VTpass bill payments
VTPASS_BILLS_ENABLED = os.getenv("VTPASS_BILLS_ENABLED", "False").lower() == "true"
VTPASS_TEST_MODE = os.getenv("VTPASS_TEST_MODE", "True").lower() == "true"
VTPASS_API_KEY = os.getenv("VTPASS_API_KEY", "")
VTPASS_PUBLIC_KEY = os.getenv("VTPASS_PUBLIC_KEY", "")
VTPASS_AIRTIME_ENABLED = os.getenv("VTPASS_AIRTIME_ENABLED", "False").lower() == "true"
VTPASS_SECRET_KEY = os.getenv("VTPASS_SECRET_KEY", "")

WALLET_WITHDRAWALS_ENABLED = os.getenv("WALLET_WITHDRAWALS_ENABLED", "False").lower() == "true"

DATA_QUOTE_GUARD_ENABLED = os.getenv("DATA_QUOTE_GUARD_ENABLED", "False").lower() == "true"

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "")
