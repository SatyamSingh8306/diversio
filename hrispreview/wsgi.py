"""WSGI config for the HRIS import preview project."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hrispreview.settings")
application = get_wsgi_application()