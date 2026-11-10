import csv
from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Movie
from library.forms import CollectionForm, UserSettingsForm
from library.models import Collection, CollectionItem, LibraryEntry, OwnedDisc, UserSettings


@login_required
def library_page(request):
    status = request.GET.get("status", "all")
    entries = LibraryEntry.objects.filter(user=request.user).select_related("movie").prefetch_related(
        "movie__genres", "movie__ratings"
    )
    sort = request.GET.get("sort", "added")
    if status in LibraryEntry.Status.values:
        entries = entries.filter(status=status)
    elif status == "favorites":
        entries = entries.filter(is_favorite=True)
    else:
        status = "all"
    sort_options = {
        "added": "-added_at",
        "rating": "-personal_rating",
        "watched": "-watched_at",
        "title": "movie__title_original",
    }
    entries = entries.order_by(sort_options.get(sort, "-added_at"))
    watched_entries = LibraryEntry.objects.filter(
        user=request.user,
        status=LibraryEntry.Status.WATCHED,
        watched_at__isnull=False,
    ).select_related("movie").prefetch_related("movie__genres")
    month_counts = Counter(entry.watched_at.strftime("%Y-%m") for entry in watched_entries)
    genre_counts = Counter(
        genre.name
        for entry in watched_entries
        for genre in entry.movie.genres.all()
    )
    months = sorted(month_counts)[-12:]
    owned_discs = list(OwnedDisc.objects.filter(user=request.user).select_related("movie", "release"))
    owned_4k_count = sum(
        1 for owned in owned_discs
        if owned.release and owned.release.disc_format == "uhd_4k"
    )
    owned_dolby_vision_count = sum(
        1 for owned in owned_discs
        if owned.release and any("dolby vision" in value.lower() for value in owned.release.hdr_formats)
    )
    return render(request, "library/library.html", {
        "entries": entries,
        "status": status,
        "sort": sort,
        "owned_discs": owned_discs,
        "owned_4k_count": owned_4k_count,
        "owned_dolby_vision_count": owned_dolby_vision_count,
        "collections": Collection.objects.filter(user=request.user),
        "watched_chart": {"labels": months, "values": [month_counts[month] for month in months]},
        "genre_chart": {"labels": list(genre_counts), "values": list(genre_counts.values())},
    })


@login_required
def collections_page(request):
    collections = Collection.objects.filter(user=request.user).prefetch_related("collectionitem_set__movie")
    return render(request, "library/collections.html", {"collections": collections})


@login_required
@require_POST
def create_collection(request):
    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, "Collection name is required.")
    elif len(name) > 100:
        messages.error(request, "Collection name must be 100 characters or fewer.")
    else:
        _, created = Collection.objects.get_or_create(user=request.user, name=name)
        messages.success(request, "Collection created." if created else "That collection already exists.")
    return redirect("collections")


@login_required
@require_POST
def edit_collection(request, pk):
    collection = get_object_or_404(Collection, pk=pk, user=request.user)
    form = CollectionForm(request.POST, instance=collection)
    if form.is_valid():
        duplicate = Collection.objects.filter(
            user=request.user,
            name=form.cleaned_data["name"],
        ).exclude(pk=collection.pk).exists()
        if duplicate:
            messages.error(request, "You already have a collection with that name.")
        else:
            form.save()
            messages.success(request, "Collection saved.")
    else:
        messages.error(request, "Enter a valid collection name.")
    return redirect("collections")


@login_required
@require_POST
def move_collection_item(request, pk, direction):
    collection = get_object_or_404(Collection, pk=pk, user=request.user)
    item_id = request.POST.get("item_id")
    items = list(CollectionItem.objects.filter(collection=collection).order_by("position", "pk"))
    index = next((index for index, item in enumerate(items) if str(item.pk) == item_id), None)
    offset = -1 if direction == "up" else 1
    neighbor_index = index + offset if index is not None else -1
    if direction not in {"up", "down"} or not 0 <= neighbor_index < len(items):
        return redirect("collections")
    item = items.pop(index)
    items.insert(neighbor_index, item)
    with transaction.atomic():
        for position, collection_item in enumerate(items):
            collection_item.position = position
        CollectionItem.objects.bulk_update(items, ["position"])
    return redirect("collections")


@login_required
@require_POST
def toggle_owned_disc(request, movie_id):
    movie = get_object_or_404(Movie, pk=movie_id)
    release_id = request.POST.get("release_id") or None
    release = None
    if release_id:
        release = get_object_or_404(movie.disc_releases, pk=release_id)
    existing = OwnedDisc.objects.filter(user=request.user, movie=movie, release=release).first()
    if existing:
        existing.delete()
        messages.success(request, "Disc removed from your owned collection.")
    else:
        OwnedDisc.objects.create(user=request.user, movie=movie, release=release)
        messages.success(request, "Disc added to your owned collection.")
    return redirect("movie-detail", pk=movie.pk)


@login_required
def export_library(request):
    entries = LibraryEntry.objects.filter(user=request.user).select_related("movie")
    status = request.GET.get("status", "")
    if status in LibraryEntry.Status.values:
        entries = entries.filter(status=status)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="kino-library.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["title", "original_title", "year", "status", "watched_at", "personal_rating", "favorite"])
    for entry in entries.order_by("movie__title_original"):
        writer.writerow([
            entry.movie.title_en or entry.movie.title_original,
            entry.movie.title_original,
            entry.movie.release_year or "",
            entry.get_status_display(),
            entry.watched_at.isoformat() if entry.watched_at else "",
            entry.personal_rating or "",
            entry.is_favorite,
        ])
    return response


@login_required
def settings_page(request):
    preferences, _ = UserSettings.objects.get_or_create(user=request.user)
    form = UserSettingsForm(request.POST or None, instance=preferences)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settings saved.")
        return redirect("settings")
    providers = [
        ("TMDB", bool(settings.TMDB_API_KEY)),
        ("OMDb", bool(settings.OMDB_API_KEY)),
        ("Kinopoisk", bool(settings.KINOPOISK_API_KEY)),
    ]
    return render(request, "library/settings.html", {"form": form, "providers": providers})


@login_required
@require_POST
def toggle_collection_movie(request, pk, movie_id):
    collection = get_object_or_404(Collection, pk=pk, user=request.user)
    movie = get_object_or_404(Movie, pk=movie_id)
    item, created = CollectionItem.objects.get_or_create(collection=collection, movie=movie)
    if not created:
        item.delete()
    messages.success(request, "Collection updated.")
    return redirect("movie-detail", pk=movie.pk)