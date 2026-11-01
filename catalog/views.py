from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.paginator import Paginator
from django.db.models import DecimalField, Exists, Min, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalog.models import DiscRelease, Genre, Movie, Rating, ReleaseDate, StreamingAvailability
from library.models import Collection, CollectionItem, LibraryEntry


def _movies_with_rating_strips(queryset):
    movies = list(queryset)
    movie_ids = [movie.pk for movie in movies]
    latest_by_source = {}
    rating_rows = Rating.objects.filter(movie_id__in=movie_ids).order_by(
        "movie_id", "source", "-fetched_at"
    )
    for rating in rating_rows:
        latest_by_source.setdefault((rating.movie_id, rating.source), rating)
    for movie in movies:
        movie.rating_strip = [
            latest_by_source[(movie.pk, source)]
            for source in Rating.Source.values
            if (movie.pk, source) in latest_by_source
        ]
    return movies


def _release_shelf(release_type, *, country, start_date=None, end_date=None, future=False):
    releases = ReleaseDate.objects.filter(
        release_type=release_type,
        country=country,
    )
    if future:
        releases = releases.filter(release_date__gt=timezone.localdate())
    else:
        releases = releases.filter(release_date__lte=timezone.localdate())
    if start_date:
        releases = releases.filter(release_date__gte=start_date)
    if end_date:
        releases = releases.filter(release_date__lte=end_date)
    return Movie.objects.filter(release_dates__in=releases).annotate(
        shelf_date=Min("release_dates__release_date", filter=Q(release_dates__in=releases))
    ).order_by("shelf_date", "title_original").distinct()[:8]


def home(request):
    today = timezone.localdate()
    country = request.GET.get("country", "uz").lower()
    if country not in {"uz", "ru", "us"}:
        country = "uz"
    shelves = [
        ("In cinemas now", _release_shelf(
            ReleaseDate.ReleaseType.THEATRICAL,
            country=country,
            start_date=today - timedelta(days=60),
        )),
        ("New on digital", _release_shelf(
            ReleaseDate.ReleaseType.DIGITAL,
            country=country,
            start_date=today - timedelta(days=30),
        )),
        ("New on disc", _release_shelf(
            ReleaseDate.ReleaseType.PHYSICAL,
            country=country,
            start_date=today - timedelta(days=60),
        )),
        ("Coming soon", _release_shelf(
            ReleaseDate.ReleaseType.THEATRICAL,
            country=country,
            future=True,
        )),
    ]
    all_movies = []
    for _, movies in shelves:
        all_movies.extend(movies)
    rating_movies = _movies_with_rating_strips({movie.pk: movie for movie in all_movies}.values())
    rating_map = {movie.pk: movie.rating_strip for movie in rating_movies}
    for _, movies in shelves:
        for movie in movies:
            movie.rating_strip = rating_map.get(movie.pk, [])
    return render(request, "catalog/home.html", {"shelves": shelves, "country": country})


def browse(request):
    queryset = Movie.objects.prefetch_related("genres").all()
    search_term = request.GET.get("q", "").strip()
    if search_term:
        queryset = queryset.filter(
            Q(title_original__icontains=search_term)
            | Q(title_en__icontains=search_term)
            | Q(title_ru__icontains=search_term)
            | Q(title_uz__icontains=search_term)
        )

    genre = request.GET.get("genre", "").strip()
    if genre:
        queryset = queryset.filter(genres__slug=genre)
    year = request.GET.get("year", "").strip()
    if year.isdigit():
        queryset = queryset.filter(release_year=int(year))
    language = request.GET.get("language", "").strip()
    if language:
        queryset = queryset.filter(original_language__iexact=language)

    imdb_score = request.GET.get("min_imdb", "").strip()
    if imdb_score:
        try:
            minimum = Decimal(imdb_score)
            if Decimal("0") <= minimum <= Decimal("100"):
                latest_imdb = Rating.objects.filter(
                    movie_id=OuterRef("pk"), source=Rating.Source.IMDB
                ).order_by("-fetched_at").values("score")[:1]
                queryset = queryset.annotate(
                    latest_imdb=Subquery(latest_imdb, output_field=DecimalField(max_digits=5, decimal_places=2))
                ).filter(latest_imdb__gte=minimum)
        except InvalidOperation:
            pass

    if request.GET.get("has_4k") == "1":
        four_k_release = DiscRelease.objects.filter(movie_id=OuterRef("pk"), disc_format=DiscRelease.Format.UHD_4K)
        queryset = queryset.annotate(has_4k_release=Exists(four_k_release)).filter(has_4k_release=True)

    streaming_country = request.GET.get("streaming_country", "").lower()
    if streaming_country:
        availability = StreamingAvailability.objects.filter(
            movie_id=OuterRef("pk"), country=streaming_country
        )
        queryset = queryset.annotate(has_streaming=Exists(availability)).filter(has_streaming=True)

    sort_options = {
        "title": "title_original",
        "year_desc": "-release_year",
        "year_asc": "release_year",
    }
    sort = request.GET.get("sort", "title")
    queryset = queryset.order_by(sort_options.get(sort, "title_original"), "pk").distinct()
    paginator = Paginator(queryset, 24)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _movies_with_rating_strips(page_obj.object_list)
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(request, "catalog/browse.html", {
        "page_obj": page_obj,
        "genres": Genre.objects.order_by("name"),
        "sort": sort,
        "querystring": query_params.urlencode(),
        "streaming_countries": settings.DEFAULT_STREAMING_COUNTRIES,
    })


def movie_detail(request, pk):
    movie = get_object_or_404(
        Movie.objects.prefetch_related(
            "genres",
            Prefetch("credits__person"),
            "ratings",
            "release_dates",
            "disc_releases",
            "streaming_options",
        ),
        pk=pk,
    )
    library_entry = None
    collections = []
    if request.user.is_authenticated:
        library_entry = LibraryEntry.objects.filter(user=request.user, movie=movie).first()
        collections = Collection.objects.filter(user=request.user).order_by("name")
    return render(request, "catalog/detail.html", {
        "movie": movie,
        "credits": movie.credits.select_related("person").all(),
        "ratings": movie.ratings.all(),
        "release_dates": movie.release_dates.all(),
        "disc_releases": movie.disc_releases.all(),
        "streaming_options": movie.streaming_options.all(),
        "library_entry": library_entry,
        "collections": collections,
        "collection_items": CollectionItem.objects.filter(
            collection__user=request.user, movie=movie
        ).select_related("collection") if request.user.is_authenticated else [],
    })


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")
    return render(request, "registration/register.html", {"form": form})


@login_required
@require_POST
def update_library_entry(request, pk):
    movie = get_object_or_404(Movie, pk=pk)
    action = request.POST.get("action")
    if action not in {"watchlist", "watched", "favorite", "remove"}:
        messages.error(request, "Choose a valid library action.")
        return redirect("movie-detail", pk=movie.pk)
    entry, _ = LibraryEntry.objects.get_or_create(user=request.user, movie=movie)
    if action == "watchlist":
        entry.status = LibraryEntry.Status.WATCHLIST
        entry.watched_at = None
    elif action == "watched":
        entry.status = LibraryEntry.Status.WATCHED
        entry.watched_at = timezone.localdate()
    elif action == "favorite":
        entry.is_favorite = not entry.is_favorite
    elif action == "remove":
        entry.delete()
        messages.success(request, "Removed from your library.")
        return redirect("movie-detail", pk=movie.pk)
    entry.save()
    messages.success(request, "Your library was updated.")
    return redirect("movie-detail", pk=movie.pk)