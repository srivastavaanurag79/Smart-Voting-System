from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r"^details/(?P<id>[\w-]+)/$", views.details, name="details"),
]
