from django.urls import path

from catalog import views

urlpatterns = [
    path("", views.home, name="home"),
    path("browse/", views.browse, name="movie-browse"),
    path("movies/", views.browse, name="movie-browse-legacy"),
    path("movie/<int:pk>/", views.movie_detail, name="movie-detail"),
    path("movie/<int:pk>/refresh/", views.queue_movie_refresh, name="movie-refresh"),
    path("movie/import/", views.queue_tmdb_import, name="movie-import"),
    path("movies/<int:pk>/", views.movie_detail, name="movie-detail-legacy"),
    path("movies/<int:pk>/library/", views.update_library_entry, name="library-entry-update"),
    path("person/<int:pk>/", views.person_detail, name="person-detail"),
    path("person/<int:pk>/import/", views.queue_person_filmography, name="person-import"),
    path("compare/", views.compare, name="compare"),
]