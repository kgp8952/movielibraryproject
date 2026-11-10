from django.urls import path

from catalog import views

urlpatterns = [
    path("", views.home, name="home"),
    path("browse/", views.browse, name="movie-browse"),
    path("movies/", views.browse, name="movie-browse-legacy"),
    path("movie/<int:pk>/", views.movie_detail, name="movie-detail"),
    path("movies/<int:pk>/", views.movie_detail, name="movie-detail-legacy"),
    path("movies/<int:pk>/library/", views.update_library_entry, name="library-entry-update"),
    path("person/<int:pk>/", views.person_detail, name="person-detail"),
    path("compare/", views.compare, name="compare"),
]