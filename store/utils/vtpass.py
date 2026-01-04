# ResultPin/store/utils/vtpass.py

import uuid
import requests
import datetime
import pytz
from django.conf import settings

# Determine base URL based on test mode
BASE_URL = "https://sandbox.vtpass.com/api/" if getattr(settings, 'VTPASS_TEST_MODE', True) else "https://vtpass.com/api/"

def generate_vtpass_request_id():
    """
    Generate a valid request_id exactly as required by VTpass.
    Format: YYYYMMDDHHMM + random alphanumeric suffix
    Timezone: Africa/Lagos (GMT+1)
    """
    # Get current time in Lagos timezone
    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.datetime.now(lagos_tz)

    # First 12 digits: YYYYMMDDHHMM
    prefix = now.strftime('%Y%m%d%H%M')  # e.g., 202601031445 for Jan 3, 2026 at 14:45

    # Add a unique suffix (12+ characters total guaranteed)
    suffix = uuid.uuid4().hex[:12]  # 12 hex chars = safe and alphanumeric

    request_id = prefix + suffix  # Example: 202601031445a1b2c3d4e5f6

    return request_id


def vtpass_call(endpoint: str, data: dict | None = None, method: str = "POST"):
    """
    Call any VTpass API endpoint with correct headers and valid request_id.
    """
    url = BASE_URL + endpoint

    headers = {
        "api-key": settings.VTPASS_API_KEY,
        "Content-Type": "application/json",
    }

    if method == "POST":
        headers["secret-key"] = settings.VTPASS_SECRET_KEY

        if data is None:
            data = {}

        # Inject correct request_id
        data["request_id"] = generate_vtpass_request_id()

    elif method == "GET":
        headers["public-key"] = settings.VTPASS_PUBLIC_KEY

    try:
        response = requests.request(method, url, json=data, headers=headers, timeout=40)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {
            "code": "099",
            "response_description": f"Network error: {str(e)}"
        }
    except ValueError:
        return {
            "code": "099",
            "response_description": "Invalid JSON response from VTpass"
        }