import os
from dotenv import load_dotenv
from django.core.mail import send_mail
from django.conf import settings

load_dotenv()

settings.configure(
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend',
    EMAIL_HOST = 'smtp.gmail.com',
    EMAIL_PORT = 587,
    EMAIL_USE_TLS = True,
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER'),
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD'),
)

send_mail(
    'Test OTP',
    'Your OTP is 123456',
    os.getenv('EMAIL_HOST_USER'),
    [os.getenv('EMAIL_HOST_USER')],
    fail_silently=False,
)
print("Email sent!")