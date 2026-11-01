from django.urls import path

from catalog import views

urlpatterns = [
    path("", views.home, name="home"),
    path("movies/", views.browse, name="movie-browse"),
    path("movies/<int:pk>/", views.movie_detail, name="movie-detail"),
    path("movies/<int:pk>/library/", views.update_library_entry, name="library-entry-update"),
]