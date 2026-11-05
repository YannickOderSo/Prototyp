"""Einstellungen des Cockpits.

Alle umgebungsabhängigen Werte kommen aus Umgebungsvariablen (django-environ).
Eine Beispielbelegung steht in `.env.example`. Geheimnisse gehören nie ins Repository.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
_env_datei = BASE_DIR / ".env"
if _env_datei.exists():
    environ.Env.read_env(str(_env_datei))

DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env.str("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# Öffentliche Basis-URL, z. B. für Links in Mails und Webhook-Callbacks
BASIS_URL = env.str("COCKPIT_BASIS_URL", default="http://localhost:8000").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts",
    "audit",
    "jobs",
    "connectors",
    "ledger",
    "dunning",
    "capture",
    "reports",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "accounts.middleware.FirmaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "web.middleware.SicherheitsHeaderMiddleware",
]

ROOT_URLCONF = "cockpit.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web.context.seite",
            ],
        },
    },
]

WSGI_APPLICATION = "cockpit.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://cockpit:cockpit@localhost:5432/cockpit"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache: Datenbank-Cache, damit Rate-Limits über alle Prozesse gelten (kein Redis nötig)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cockpit_cache",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "de"
LANGUAGES = [("de", "Deutsch")]
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Uploads liegen außerhalb des Webroots und werden nie direkt ausgeliefert
DATEIABLAGE = Path(env.str("COCKPIT_DATEIABLAGE", default=str(BASE_DIR / "var" / "dateien")))

# Sitzung und Cookies
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", default=not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_SSL_REDIRECT = env.bool("DJANGO_SSL_REDIRECT", default=not DEBUG)
# Interne Health-Checks (Docker, Uptime im internen Netz) laufen ohne TLS
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS-Preload ist eine Domain-Entscheidung des Teams, nicht des Codes
SILENCED_SYSTEM_CHECKS = ["security.W021"]

# Hinter Caddy: Client-IP aus X-Forwarded-For (nur aktivieren, wenn die App nicht direkt erreichbar ist)
HINTER_PROXY = env.bool("COCKPIT_HINTER_PROXY", default=False)
RATELIMIT_VIEW = "accounts.drosselung.zu_viele_versuche"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "web:start"

# Verschlüsselung von Geheimnissen (API-Schlüssel, TOTP, SMTP) mit MultiFernet.
# Erster Schlüssel verschlüsselt, alle Schlüssel entschlüsseln (Rotation siehe Betriebshandbuch).
FERNET_KEYS = env.list("COCKPIT_FERNET_KEYS")

# E-Mail (Plattform-Versand über einen EU-Anbieter)
EMAIL_BACKEND = env.str("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env.str("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=30)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="cockpit@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Externe Dienste, ausschließlich EU-Endpunkte (ADR-005)
LEXWARE_BASIS_URL = env.str("LEXWARE_BASIS_URL", default="https://api.lexware.io")
MISTRAL_BASIS_URL = env.str("MISTRAL_BASIS_URL", default="https://api.mistral.ai")
MISTRAL_API_KEY = env.str("MISTRAL_API_KEY", default="")
MISTRAL_MODELL = env.str("MISTRAL_MODELL", default="voxtral-mini-latest")
BEDROCK_REGION = env.str("BEDROCK_REGION", default="eu-central-1")
BEDROCK_MODELL = env.str("BEDROCK_MODELL", default="eu.anthropic.claude-sonnet-4-5-20250929-v1:0")

# Fehlererfassung (GlitchTip selbst gehostet oder Sentry mit EU-Datenhaltung)
SENTRY_DSN = env.str("SENTRY_DSN", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "web.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

AUTH_USER_MODEL = "accounts.Nutzer"
