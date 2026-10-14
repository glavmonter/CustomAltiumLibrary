from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    path("", views.component_list, name="components"),
    path("c/<str:design_item_id>/", views.component_detail, name="component"),
    path("media/<int:pk>/", views.media, name="media"),
    path("api/library-file/analyze/", views.analyze_library_file, name="analyze_library_file"),
]
