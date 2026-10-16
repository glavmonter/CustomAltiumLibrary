from django.urls import path

from . import api, views

app_name = "library"

urlpatterns = [
    path("", views.component_list, name="components"),
    path("c/<str:design_item_id>/", views.component_detail, name="component"),
    path("media/<int:pk>/", views.media, name="media"),
    path("api/library-file/analyze/", views.analyze_library_file, name="analyze_library_file"),
    # внешнее API (ключ приложения), см. library/api.py
    path("api/v1/openapi.yaml", api.openapi_spec, name="api_openapi"),
    path("api/v1/references/", api.references, name="api_references"),
    path("api/v1/components/", api.components, name="api_components"),
    path("api/v1/components/bulk/", api.bulk_components, name="api_bulk_components"),
]
