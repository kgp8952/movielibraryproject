from django.urls import path

from library import views

urlpatterns = [
    path("", views.library_page, name="library"),
    path("collections/", views.collections_page, name="collections"),
    path("collections/create/", views.create_collection, name="collection-create"),
    path("collections/<int:pk>/movies/<int:movie_id>/", views.toggle_collection_movie, name="collection-toggle-movie"),
]