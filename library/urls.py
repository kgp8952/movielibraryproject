from django.urls import path

from library import views

urlpatterns = [
    path("", views.library_page, name="library"),
    path("settings/", views.settings_page, name="settings-legacy"),
    path("export.csv", views.export_library, name="library-export"),
    path("collections/", views.collections_page, name="collections"),
    path("collections/create/", views.create_collection, name="collection-create"),
    path("collections/<int:pk>/edit/", views.edit_collection, name="collection-edit"),
    path("collections/<int:pk>/move/<str:direction>/", views.move_collection_item, name="collection-move"),
    path("collections/<int:pk>/movies/<int:movie_id>/", views.toggle_collection_movie, name="collection-toggle-movie"),
    path("movies/<int:movie_id>/disc/", views.toggle_owned_disc, name="owned-disc-toggle"),
]