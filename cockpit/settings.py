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
# Rotation: alten Schlüssel hierhin verschieben, damit Sitzungen und Links gültig bleiben (Betriebshandbuch)
SECRET_KEY_FALLBACKS = env.list("DJANGO_SECRET_KEY_FALLBACKS", default=[])
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
    "datenimport",
    "telefon",
    "quellen",
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

# Uploads: je Datei bis 25 MB, je Anfrage bis 50 MB (E1); große Dateien gehen in temporäre Dateien
DATA_UPLOAD_MAX_MEMORY_SIZE = 52 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 10

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
# Weitere nur bewusst und begründet stummschalten (z. B. in der CI cockpit.W001, solange die Rechtstexte fehlen)
SILENCED_SYSTEM_CHECKS = ["security.W021", *env.list("COCKPIT_CHECKS_STUMM", default=[])]

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
# Geheimes Token für Zustellmeldungen (Bounces) des SMTP-Anbieters: /hooks/zustellung/<token>/
ZUSTELLUNG_WEBHOOK_TOKEN = env.str("ZUSTELLUNG_WEBHOOK_TOKEN", default="")
# Anbieter des Plattform-SMTP. "mailjet": jede Mail bekommt X-MJ-CustomID (= Message-ID), damit Mailjet-Ereignisse
# (Bounce, blockiert, Spam) über den Zustellungs-Webhook dem Versand zugeordnet werden (ADR-012, Vorschlag)
MAILVERSAND_ANBIETER = env.str("MAILVERSAND_ANBIETER", default="").strip().lower()

# Externe Dienste, ausschließlich EU-Endpunkte (ADR-005)
LEXWARE_BASIS_URL = env.str("LEXWARE_BASIS_URL", default="https://api.lexware.io")
MISTRAL_BASIS_URL = env.str("MISTRAL_BASIS_URL", default="https://api.mistral.ai")
MISTRAL_API_KEY = env.str("MISTRAL_API_KEY", default="")
MISTRAL_MODELL = env.str("MISTRAL_MODELL", default="voxtral-mini-latest")
BEDROCK_REGION = env.str("BEDROCK_REGION", default="eu-central-1")
# EU-Inferenzprofil (Präfix "eu."): Routing nur innerhalb der EU. "global." und "us." blockiert ein Systemcheck.
BEDROCK_MODELL = env.str("BEDROCK_MODELL", default="eu.anthropic.claude-sonnet-5-5")
# KI-Telefonassistent (ADR-010): schnelles Modell, nur EU-Profil (Systemcheck cockpit.E005); leer = BEDROCK_MODELL
TELEFON_MODELL = env.str("TELEFON_MODELL", default="eu.anthropic.claude-haiku-5-5")
# Sprachausgabe: "voxtral" (Mistral EU, Standard) oder "piper" (nur mit freigegebener Stimme, Offene-Fragen.md)
TELEFON_SPRACHAUSGABE = env.str("TELEFON_SPRACHAUSGABE", default="voxtral")
MISTRAL_TTS_MODELL = env.str("MISTRAL_TTS_MODELL", default="voxtral-mini-tts-3-0")
MISTRAL_TTS_STIMME = env.str("MISTRAL_TTS_STIMME", default="voice_481")  # „Heidi“, deutsche Voxtral-3-Stimme
# Eigenes Monatslimit des Telefons je Firma (getrennt vom KI-Limit der Erfassung); darüber Ausfallbetrieb ohne KI
TELEFON_LIMIT_GESPRAECHE_MONAT = env.int("TELEFON_LIMIT_GESPRAECHE_MONAT", default=400)
TELEFON_ASTERISK_TOKEN = env.str("TELEFON_ASTERISK_TOKEN", default="")
TELEFON_AUDIOSOCKET_HOST = env.str("TELEFON_AUDIOSOCKET_HOST", default="127.0.0.1")
TELEFON_AUDIOSOCKET_PORT = env.int("TELEFON_AUDIOSOCKET_PORT", default=9092)
PIPER_BEFEHL = env.str("PIPER_BEFEHL", default="piper")
PIPER_MODELL = env.str("PIPER_MODELL", default="")

# Belegpostfach (E2): Sammelpostfach mit Plus-Adressen je Firma, Abruf per IMAP (TLS)
BELEGPOSTFACH_ADRESSE = env.str("BELEGPOSTFACH_ADRESSE", default="")  # z. B. belege@cockpit.example
BELEGPOSTFACH_IMAP_HOST = env.str("BELEGPOSTFACH_IMAP_HOST", default="")
BELEGPOSTFACH_IMAP_PORT = env.int("BELEGPOSTFACH_IMAP_PORT", default=993)
BELEGPOSTFACH_IMAP_BENUTZER = env.str("BELEGPOSTFACH_IMAP_BENUTZER", default="")
BELEGPOSTFACH_IMAP_PASSWORT = env.str("BELEGPOSTFACH_IMAP_PASSWORT", default="")
BELEGPOSTFACH_IMAP_ORDNER = env.str("BELEGPOSTFACH_IMAP_ORDNER", default="INBOX")
# authserv-id des eigenen Mailservers: nur dessen Authentication-Results zählen
BELEGPOSTFACH_AUTHSERV_ID = env.str("BELEGPOSTFACH_AUTHSERV_ID", default="")

# Kostenlimit der KI je Firma und Monat
KI_LIMIT_VORGAENGE_MONAT = env.int("KI_LIMIT_VORGAENGE_MONAT", default=300)
KI_LIMIT_TOKENS_MONAT = env.int("KI_LIMIT_TOKENS_MONAT", default=3_000_000)

# Fehlererfassung (GlitchTip selbst gehostet oder Sentry mit EU-Datenhaltung)
SENTRY_DSN = env.str("SENTRY_DSN", default="")
SENTRY_UMGEBUNG = env.str("SENTRY_UMGEBUNG", default="produktion")
COCKPIT_VERSION = env.str("COCKPIT_VERSION", default="") or None
if SENTRY_DSN:
    from cockpit.fehlererfassung import einrichten, erlaubter_host

    if erlaubter_host(SENTRY_DSN):  # sonst meldet der Systemcheck cockpit.E004 den Fehler
        einrichten(SENTRY_DSN, SENTRY_UMGEBUNG, COCKPIT_VERSION)

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
