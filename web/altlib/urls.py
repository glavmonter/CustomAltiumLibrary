from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Библиотека компонентов Altium"
admin.site.site_title = "Библиотека Altium"
admin.site.index_title = "Редактирование библиотеки"
admin.site.site_url = "/"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("library.urls")),
]
