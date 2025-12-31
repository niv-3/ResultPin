"""
Django settings for core project.
"""

from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv
import os


load_dotenv()

# ==============================
# BASE DIR
# ==============================
BASE_DIR = Path(__file__).resolve().parent.parent


# ==============================
# SECURITY
# ==============================
SECRET_KEY = os.getenv(
    'SECRET_KEY',
    'django-insecure-ao%__!xyv(_d()8b5i)d!6#cq(+$)jcs4sy*9auy!@m2gb-uq4'
)

DEBUG = True

ALLOWED_HOSTS = ['*']  # Change in production


# ==============================
# APPLICATIONS
# ==============================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'store',
    'django.contrib.humanize',
    'rest_framework',
    'crispy_forms',
    'crispy_bootstrap5',
]


# ==============================
# MIDDLEWARE
# ==============================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# ==============================
# URL / WSGI
# ==============================
ROOT_URLCONF = 'core.urls'

WSGI_APPLICATION = 'core.wsgi.application'


# ==============================
# TEMPLATES
# ==============================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',

        # 🔧 FIXED typo: stoer → store
        'DIRS': [BASE_DIR / 'store' / 'templates'],

        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


# ==============================
# DATABASE
# ==============================
DATABASES = {
    'default': dj_database_url.parse(os.getenv('DATABASE_URL'))
}


# ==============================
# AUTH / PASSWORDS
# ==============================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = 'store.User'


# ==============================
# INTERNATIONALIZATION
# ==============================
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True


# ==============================
# STATIC FILES
# ==============================
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')


# ==========================
# EMAIL CONFIGURATION (GMAIL)
# ==========================

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True

EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")

DEFAULT_FROM_EMAIL = "ResultPin <resultpin.solutions@gmail.com>"



# ==============================
# PAYSTACK
# ==============================
# settings.py
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")




# ==============================
# TERMII (SMS)
# ==============================
TERMII_API_KEY = os.getenv('TERMII_API_KEY')
TERMII_SENDER_ID = os.getenv('TERMII_SENDER_ID', 'ResultPin')


# ==============================
# VTPASS (SANDBOX) – WAEC PINS
# ==============================
VTPASS_API_KEY = "31776810f5c6873b50a50e72a65313a3"
VTPASS_PUBLIC_KEY = "PK_153c4b2d250a1135d25d4bc209baf1e201dea7a7925"
VTPASS_SECRET_KEY = "SK_82749e1802a0c5d9b2019ebeb230c9eecbbb0953ba5"

# Sandbox toggle (VERY IMPORTANT)
VTPASS_TEST_MODE = True


# ==============================
# EPINS (OPTIONAL / FALLBACK)
# ==============================
EPINS_API_KEY = os.getenv('EPINS_API_KEY')


# ==============================
# TWILIO (OPTIONAL)
# ==============================
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')


# ==============================
# DEFAULTS
# ==============================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"