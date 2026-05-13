"""
URL configuration for the config project module.

The ``urlpatterns`` list routes URLs to views. For more information, see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
"""
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import FileResponse, Http404
from django.urls import include, path


def static_text_asset(filename, content_type):
    asset_path = settings.BASE_DIR / "static" / filename
    if not asset_path.exists():
        raise Http404(f"{filename} not found")
    response = FileResponse(asset_path.open("rb"), content_type=content_type)
    if filename == "service-worker.js":
        response["Service-Worker-Allowed"] = "/"
        response["Cache-Control"] = "no-cache"
    return response


def service_worker(request):
    return static_text_asset("service-worker.js", "application/javascript")


def webmanifest(request):
    return static_text_asset("manifest.webmanifest", "application/manifest+json")

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("service-worker.js", service_worker, name="service_worker"),
    path("static/manifest.webmanifest", webmanifest, name="webmanifest"),
]

urlpatterns += i18n_patterns(
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("core.urls")),
)
