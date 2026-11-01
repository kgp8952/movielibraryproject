from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Movie
from library.models import Collection, CollectionItem, LibraryEntry, OwnedDisc


@login_required
def library_page(request):
    status = request.GET.get("status", "all")
    entries = LibraryEntry.objects.filter(user=request.user).select_related("movie").prefetch_related(
        "movie__genres", "movie__ratings"
    )
    if status in LibraryEntry.Status.values:
        entries = entries.filter(status=status)
    elif status == "favorites":
        entries = entries.filter(is_favorite=True)
    else:
        status = "all"
    return render(request, "library/library.html", {
        "entries": entries,
        "status": status,
        "owned_discs": OwnedDisc.objects.filter(user=request.user).select_related("movie", "release"),
        "collections": Collection.objects.filter(user=request.user),
    })


@login_required
def collections_page(request):
    collections = Collection.objects.filter(user=request.user).prefetch_related("movies")
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
def toggle_collection_movie(request, pk, movie_id):
    collection = get_object_or_404(Collection, pk=pk, user=request.user)
    movie = get_object_or_404(Movie, pk=movie_id)
    item, created = CollectionItem.objects.get_or_create(collection=collection, movie=movie)
    if not created:
        item.delete()
    messages.success(request, "Collection updated.")
    return redirect("movie-detail", pk=movie.pk)