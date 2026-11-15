from django.urls import path

from sync import views

urlpatterns = [
	path("", views.sync_status, name="sync-status"),
	path("run/", views.run_now, name="sync-run-now"),
]