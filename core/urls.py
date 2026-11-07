from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.views.generic import TemplateView


def health(request):
    return HttpResponse("ok", content_type="text/plain")

urlpatterns = [
    path("health/", health),
    path(
        "manifest.webmanifest",
        TemplateView.as_view(
            template_name="store/manifest.webmanifest",
            content_type="application/manifest+json",
        ),
        name="web_app_manifest",
    ),
    path('admin/', admin.site.urls),
    path('', include('store.urls')),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
