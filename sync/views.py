from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from library.models import UserSettings
from sync.models import ProviderCall, SyncJob
from sync.services import enqueue_job


@login_required
def sync_status(request):
    today = timezone.localdate()
    preferences = UserSettings.objects.filter(user=request.user).values_list("enabled_providers", flat=True).first()
    preferences = preferences or {"tmdb": True, "omdb": True, "kinopoisk": True, "disc": True}
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
        {"name": "disc", "configured": bool(settings.DISC_API_BASE_URL), "calls": daily_counts.get("disc", 0), "limit": None},
    ]
    for provider in providers:
        provider["usage_percent"] = min(100, round(provider["calls"] * 100 / provider["limit"])) if provider["limit"] else 0
    run_options = [
        (SyncJob.Kind.NOW_PLAYING, "Now playing", "TMDB", bool(settings.TMDB_API_KEY and preferences.get("tmdb", True))),
        (SyncJob.Kind.UPCOMING, "Upcoming", "TMDB", bool(settings.TMDB_API_KEY and preferences.get("tmdb", True))),
        (SyncJob.Kind.POPULAR, "Popular", "TMDB", bool(settings.TMDB_API_KEY and preferences.get("tmdb", True))),
        (SyncJob.Kind.REFRESH_RATINGS, "Refresh ratings", "TMDB", bool(settings.TMDB_API_KEY and preferences.get("tmdb", True))),
        (SyncJob.Kind.REFRESH_DISCS, "Refresh discs", "Disc API", bool(settings.DISC_API_BASE_URL and preferences.get("disc", True))),
    ]
    return render(request, "sync/status.html", {
        "jobs": SyncJob.objects.order_by("-created_at")[:50],
        "providers": providers,
        "run_options": run_options,
        "today": today,
    })


@login_required
@require_POST
def run_now(request):
    kind = request.POST.get("kind", "")
    allowed = {
        SyncJob.Kind.NOW_PLAYING,
        SyncJob.Kind.UPCOMING,
        SyncJob.Kind.POPULAR,
        SyncJob.Kind.REFRESH_RATINGS,
        SyncJob.Kind.REFRESH_DISCS,
    }
    if kind not in allowed:
        messages.error(request, "Select a supported sync task.")
        return redirect("sync-status")
    preferences = UserSettings.objects.filter(user=request.user).values_list("enabled_providers", flat=True).first()
    preferences = preferences or {"tmdb": True, "omdb": True, "kinopoisk": True, "disc": True}
    required_provider = "disc" if kind == SyncJob.Kind.REFRESH_DISCS else "tmdb"
    configured = settings.DISC_API_BASE_URL if required_provider == "disc" else settings.TMDB_API_KEY
    if not configured or not preferences.get(required_provider, True):
        messages.error(request, f"{required_provider.upper()} is not configured or enabled for this account.")
        return redirect("sync-status")
    payload = {
        "country": preferences.get("preferred_country", "uz"),
        "limit": 100,
        "enabled_providers": preferences,
    }
    enqueue_job(
        kind,
        payload=payload,
        idempotency_key=f"manual:{request.user.pk}:{kind}:{timezone.now().timestamp()}",
    )
    messages.success(request, f"{SyncJob.Kind(kind).label} queued.")
    return redirect("sync-status")