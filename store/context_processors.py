from django.conf import settings
from .models import ServiceCategory


def navigation(request):
    return {
        "navigation_services": ServiceCategory.objects.filter(is_active=True).order_by("order", "pk"),
        "idle_timeout_seconds": settings.SESSION_IDLE_TIMEOUT,
        "idle_activity_at": request.session.get("payvict_last_activity", 0),
    }
