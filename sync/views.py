from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from sync.models import ProviderCall, SyncJob


@login_required
def sync_status(request):
    today = timezone.localdate()
    daily_counts = {
        row["provider"]: row["total"]
        for row in ProviderCall.objects.filter(called_at__date=today)
        .values("provider")
        .annotate(total=Count("id"))
    }
    providers = [
        {"name": "tmdb", "configured": bool(settings.TMDB_API_KEY), "calls": daily_counts.get("tmdb", 0), "limit": None},
        {"name": "omdb", "configured": bool(settings.OMDB_API_KEY), "calls": daily_counts.get("omdb", 0), "limit": settings.OMDB_DAILY_LIMIT},
        {"name": "kinopoisk", "configured": bool(settings.KINOPOISK_API_KEY), "calls": daily_counts.get("kinopoisk", 0), "limit": None},
    ]
    for provider in providers:
        provider["usage_percent"] = min(100, round(provider["calls"] * 100 / provider["limit"])) if provider["limit"] else 0
    return render(request, "sync/status.html", {
        "jobs": SyncJob.objects.order_by("-created_at")[:50],
        "providers": providers,
        "today": today,
    })