import os

from .settings import *

DEBUG = False
SECRET_KEY = os.environ["SECRET_KEY"]
DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=60)}

render_hostname = os.environ["RENDER_EXTERNAL_HOSTNAME"]
ALLOWED_HOSTS = [render_hostname, *ALLOWED_HOSTS]
CSRF_TRUSTED_ORIGINS = [f"https://{render_hostname}", *CSRF_TRUSTED_ORIGINS]
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^health/$"]
SECURE_HSTS_SECONDS = 86400

BETA_BUYER_EMAILS = {
    email.strip().casefold()
    for email in os.getenv("BETA_BUYER_EMAILS", "").split(",")
    if email.strip()
}
BETA_PAYMENTS_ENABLED = (
    os.getenv("BETA_PAYMENTS_ENABLED") == "true"
    and bool(BETA_BUYER_EMAILS)
    and PAYSTACK_SECRET_KEY.startswith("sk_live_")
    and PAYSTACK_PUBLIC_KEY.startswith("pk_live_")
    and bool(os.getenv("CHEAPDATAHUB_API_KEY"))
)
VTPASS_BILLS_ENABLED = False

MIDDLEWARE = [
    MIDDLEWARE[0],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
    "core.preview.PreviewPaymentsMiddleware",
]
STORAGES["staticfiles"]["BACKEND"] = "whitenoise.storage.CompressedManifestStaticFilesStorage"
