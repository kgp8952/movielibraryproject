from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from catalog.views import register
from library.views import settings_page

urlpatterns = [
	path("admin/", admin.site.urls),
	path("settings/", settings_page, name="settings"),
	path("", include("catalog.urls")),
	path("library/", include("library.urls")),
	path("sync/", include("sync.urls")),
	path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
	path("accounts/logout/", auth_views.LogoutView.as_view(template_name="registration/logged_out.html"), name="logout"),
	path("accounts/register/", register, name="register"),
]