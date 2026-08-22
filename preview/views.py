"""Views for the HRIS import preview.

The view is deliberately thin: it reads the uploaded file, delegates all
parsing and hierarchy logic to :mod:`preview.analysis`, and renders the
result. Any analysis error becomes a clear ``400`` response instead of an
unhandled exception.
"""
from django.http import HttpResponse
from django.shortcuts import render

from .analysis import HrisError, analyze


def index(request):
    result = None
    error = None

    if request.method == "POST":
        upload = request.FILES.get("csv_file")
        if not upload:
            error = "No file was uploaded."
        else:
            try:
                content = upload.read()
                result = analyze(content)
            except HrisError as exc:
                error = str(exc)
            except Exception as exc:  # noqa: BLE001 - last-resort guard
                error = f"Unexpected error while processing upload: {exc}"

    return render(
        request,
        "preview/index.html",
        {"result": result, "error": error},
    )