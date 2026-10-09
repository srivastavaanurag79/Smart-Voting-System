from django.shortcuts import get_object_or_404, render

from .models import Records


def details(request, id):
    record = get_object_or_404(Records, id=id)
    return render(request, "details.html", {"record": record})
