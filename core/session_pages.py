from django.utils.cache import add_never_cache_headers


class SessionPageCacheMiddleware:
    """Keep account pages out of shared caches and stale browser HTTP caches."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, "user", None) and request.user.is_authenticated:
            if response.get("Content-Type", "").startswith("text/html"):
                add_never_cache_headers(response)
        return response
