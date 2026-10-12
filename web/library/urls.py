from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    path("", views.component_list, name="components"),
    path("c/<str:design_item_id>/", views.component_detail, name="component"),
    path("media/<int:pk>/", views.media, name="media"),
]
