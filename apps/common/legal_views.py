from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def terms(request):
    return render(request, "legal/terms.html")


@require_GET
def privacy(request):
    return render(request, "legal/privacy.html")


@require_GET
def open_source(request):
    return render(request, "legal/open_source.html")
