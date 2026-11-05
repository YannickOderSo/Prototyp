"""Einstellungen für die Testläufe. Nur Testwerte, keine echten Geheimnisse."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "nur-fuer-tests-kein-echtes-geheimnis")
os.environ.setdefault("COCKPIT_FERNET_KEYS", "VGVzdHNjaGx1ZXNzZWwtbnVyLWZ1ZXItVGVzdHMtMzI=")

from cockpit.settings import *  # noqa: F403
from cockpit.settings import BASE_DIR

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SILENCED_SYSTEM_CHECKS = ["security.W021", "django_ratelimit.E003", "django_ratelimit.W001"]
SECURE_SSL_REDIRECT = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
DATEIABLAGE = BASE_DIR / "var" / "test-dateien"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
LOGGING = {"version": 1, "disable_existing_loggers": False}
