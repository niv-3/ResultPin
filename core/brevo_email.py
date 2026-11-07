from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages or ():
            name, address = parseaddr(message.from_email)
            try:
                response = requests.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={"api-key": settings.BREVO_API_KEY},
                    json={
                        "sender": {"email": address, "name": name or "Payvict"},
                        "to": [{"email": parseaddr(recipient)[1]} for recipient in message.to],
                        "subject": message.subject,
                        "textContent": message.body,
                    },
                    timeout=8,
                )
                response.raise_for_status()
            except requests.RequestException:
                if not self.fail_silently:
                    raise OSError("Verification email provider unavailable.") from None
            else:
                sent += 1
        return sent
