from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.paginator import Paginator
from django.db.models import DecimalField, Exists, Max, Min, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalog.models import Credit, DiscRelease, Genre, Movie, Person, Rating, ReleaseDate, StreamingAvailability
from library.models import Collection, CollectionItem, LibraryEntry, OwnedDisc, UserSettings


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
    user_country = UserSettings.objects.filter(user=request.user).values_list("preferred_country", flat=True).first() if request.user.is_authenticated else "uz"
    country = request.GET.get("country", user_country).lower()
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

    genres = request.GET.getlist("genre")
    if genres:
        queryset = queryset.filter(genres__slug__in=genres).distinct()
    year_min = request.GET.get("year_min", "").strip()
    if year_min.isdigit():
        queryset = queryset.filter(release_year__gte=int(year_min))
    year_max = request.GET.get("year_max", "").strip()
    if year_max.isdigit():
        queryset = queryset.filter(release_year__lte=int(year_max))
    language = request.GET.get("language", "").strip()
    if language:
        queryset = queryset.filter(original_language__iexact=language)

    imdb_score = request.GET.get("min_imdb", "").strip()
    if imdb_score:
        try:
            minimum = Decimal(imdb_score)
            if Decimal("0") < minimum <= Decimal("100"):
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

    score_subqueries = {
        "imdb": Rating.Source.IMDB,
        "kinopoisk": Rating.Source.KINOPOISK,
    }
    sort = request.GET.get("sort", "release_desc")
    if sort in score_subqueries:
        latest_score = Rating.objects.filter(
            movie_id=OuterRef("pk"), source=score_subqueries[sort]
        ).order_by("-fetched_at").values("score")[:1]
        queryset = queryset.annotate(sort_score=Subquery(
            latest_score, output_field=DecimalField(max_digits=5, decimal_places=2)
        )).order_by("-sort_score", "title_original")
    else:
        if sort in {"release_desc", "release_asc"}:
            queryset = queryset.annotate(sort_release_date=Max("release_dates__release_date"))
            direction = "-" if sort == "release_desc" else ""
            queryset = queryset.order_by(f"{direction}sort_release_date", "title_original")
        else:
            sort_options = {"title": "title_original", "popularity": "-popularity"}
            queryset = queryset.order_by(sort_options.get(sort, "title_original"), "pk")
    queryset = queryset.distinct()
    paginator = Paginator(queryset, 24)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _movies_with_rating_strips(page_obj.object_list)
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(request, "catalog/browse.html", {
        "page_obj": page_obj,
        "genres": Genre.objects.order_by("name"),
        "selected_genres": genres,
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
    owned_discs = []
    settings_country = "uz"
    if request.user.is_authenticated:
        library_entry = LibraryEntry.objects.filter(user=request.user, movie=movie).first()
        collections = Collection.objects.filter(user=request.user).order_by("name")
        owned_discs = OwnedDisc.objects.filter(user=request.user, movie=movie).values_list("release_id", flat=True)
        settings_country = UserSettings.objects.filter(user=request.user).values_list("preferred_country", flat=True).first() or "uz"
    latest_ratings = {}
    for rating in movie.ratings.all():
        latest_ratings.setdefault(rating.source, rating)
    imdb_history = list(movie.ratings.filter(source=Rating.Source.IMDB).order_by("fetched_at"))
    rating_rows = [
        {"source": source, "label": label, "rating": latest_ratings.get(source)}
        for source, label in Rating.Source.choices
    ]
    return render(request, "catalog/detail.html", {
        "movie": movie,
        "credits": movie.credits.select_related("person").all(),
        "cast": movie.credits.filter(role=Credit.Role.CAST).select_related("person").order_by("credit_order")[:10],
        "directors": movie.credits.filter(role=Credit.Role.DIRECTOR).select_related("person"),
        "writers": movie.credits.filter(role=Credit.Role.WRITER).select_related("person"),
        "ratings": movie.ratings.all(),
        "latest_ratings": latest_ratings,
        "rating_rows": rating_rows,
        "imdb_history_count": len(imdb_history),
        "imdb_chart": {
            "labels": [rating.fetched_at.strftime("%Y-%m-%d") for rating in imdb_history],
            "scores": [float(rating.score) / 10 for rating in imdb_history],
        },
        "release_dates": movie.release_dates.all(),
        "disc_releases": movie.disc_releases.all(),
        "streaming_options": movie.streaming_options.filter(country=settings_country),
        "streaming_country": settings_country,
        "library_entry": library_entry,
        "owned_release_ids": list(owned_discs),
        "collections": collections,
        "collection_items": CollectionItem.objects.filter(
            collection__user=request.user, movie=movie
        ).select_related("collection") if request.user.is_authenticated else [],
    })


def person_detail(request, pk):
    person = get_object_or_404(Person, pk=pk)
    credits = Credit.objects.filter(person=person).select_related("movie").order_by(
        "-movie__release_year", "movie__title_original"
    )
    movies = list(Movie.objects.filter(credits__person=person).distinct().order_by(
        "-release_year", "title_original"
    ))
    movies = _movies_with_rating_strips(movies)
    return render(request, "catalog/person.html", {
        "person": person,
        "credits": credits,
        "movies": movies,
    })


def compare(request):
    selected_ids = request.GET.getlist("movie")[:4]
    movies = list(Movie.objects.filter(pk__in=selected_ids).prefetch_related(
        "ratings", "release_dates", "disc_releases", "genres"
    ))
    order = {str(value): index for index, value in enumerate(selected_ids)}
    movies.sort(key=lambda movie: order.get(str(movie.pk), len(order)))
    for movie in movies:
        movie.latest_ratings = {}
        for rating in movie.ratings.all():
            movie.latest_ratings.setdefault(rating.source, rating)
        movie.rating_rows = [
            {"label": label, "rating": movie.latest_ratings.get(source)}
            for source, label in Rating.Source.choices
        ]
        movie.latest_release = movie.release_dates.order_by("-release_date").first()
        movie.disc_formats = list(movie.disc_releases.values_list("disc_format", flat=True).distinct())
    return render(request, "catalog/compare.html", {
        "movies": movies,
        "movie_options": Movie.objects.order_by("title_original"),
        "selected_ids": [str(movie.pk) for movie in movies],
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
    if action == "rate":
        try:
            personal_rating = int(request.POST.get("personal_rating", ""))
        except ValueError:
            personal_rating = 0
        if not 1 <= personal_rating <= 10:
            messages.error(request, "Personal ratings must be between 1 and 10.")
            return redirect("movie-detail", pk=movie.pk)
    elif action not in {"watchlist", "watched", "favorite", "remove"}:
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
    elif action == "rate":
        entry.personal_rating = personal_rating
    elif action == "remove":
        entry.delete()
        messages.success(request, "Removed from your library.")
        return redirect("movie-detail", pk=movie.pk)
    entry.save()
    messages.success(request, "Your library was updated.")
    return redirect("movie-detail", pk=movie.pk)