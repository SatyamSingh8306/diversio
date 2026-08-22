"""Django settings for the HRIS import preview.

The application is intentionally database-less: no employee or relationship
data is persisted, so we only need the templating, form, and URL machinery.
An in-memory SQLite database is declared purely so the Django test runner
can create its test database without errors.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dev-only-insecure-key-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "preview",
]

MIDDLEWARE = []

ROOT_URLCONF = "hrispreview.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

WSGI_APPLICATION = "hrispreview.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

USE_TZ = True
LANGUAGE_CODE = "en-us"

STATIC_URL = "static/"