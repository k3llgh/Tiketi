"""
Tiketi — Django settings
Single settings file with environment-driven overrides.
Uses django-tenants for multi-tenancy (subdomain per vendor/stadium).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ── Core ─────────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost 127.0.0.1").split()

# ── django-tenants ────────────────────────────────────────────────────────────
# MUST be first in INSTALLED_APPS
SHARED_APPS = [
    "django_tenants",           # must be first

    # Shared (public schema) apps — exist once across all tenants
    "apps.accounts",            # custom user model lives here
    "apps.audit",

    # Django built-ins that live in the public schema
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",

    # Third-party shared
    "django_celery_beat",
    "django_celery_results",
    "django_extensions",
    "phonenumber_field",
]

TENANT_APPS = [
    # Per-tenant apps — each tenant gets its own schema
    "apps.events",
    "apps.tickets",
    "apps.wallet",
    "apps.buyback",
    "apps.gate",
    "apps.payments",
    "apps.notifications",

    # Django built-ins needed per-tenant
    "django.contrib.contenttypes",
    "django.contrib.auth",
]

INSTALLED_APPS = list(dict.fromkeys(SHARED_APPS + TENANT_APPS + [
    "django_htmx",
    "widget_tweaks",
    "debug_toolbar",            # stripped in production via middleware check
]))

TENANT_MODEL = "accounts.Tenant"
TENANT_DOMAIN_MODEL = "accounts.Domain"

# ── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",  # must be first
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

if DEBUG:
    MIDDLEWARE.insert(1, "debug_toolbar.middleware.DebugToolbarMiddleware")

# ── URLs & WSGI ───────────────────────────────────────────────────────────────
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

PUBLIC_SCHEMA_URLCONF = "config.urls_public"    # tiketi.co — marketing + vendor onboarding
TENANT_SUBFOLDER_PREFIX = ""                    # subdomains, not subfolders

# ── Templates ─────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.tiketi_globals",
            ],
        },
    },
]

# ── Database ──────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",  # wraps psycopg2
        "NAME": os.environ.get("DB_NAME", "tiketi"),
        "USER": os.environ.get("DB_USER", "tiketi"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

# ── Cache (Redis) ─────────────────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
        },
        "KEY_PREFIX": "tiketi",
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14      # 2 weeks
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.EmailBackend",
    "apps.accounts.backends.PhoneOTPBackend",
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",  # strongest
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # fallback
]

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Nairobi"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ALWAYS_EAGER = False    # set True in tests to run tasks synchronously
CELERY_TASK_EAGER_PROPAGATES = True

# ── Email ─────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if not DEBUG
    else "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Tiketi <noreply@tiketi.co>")

# ── Static & media ────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

USE_S3 = os.environ.get("USE_S3", "False") == "True"

if USE_S3:
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "tiketi-media")
    AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL")  # DO Spaces or R2
    AWS_S3_CUSTOM_DOMAIN = os.environ.get("AWS_S3_CUSTOM_DOMAIN")
    AWS_DEFAULT_ACL = "private"
    AWS_S3_FILE_OVERWRITE = False
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
else:
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"

# ── Internationalisation ──────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# ── Security (production) ─────────────────────────────────────────────────────
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS", "https://tiketi.co https://*.tiketi.co"
).split()

# ── Sentry ────────────────────────────────────────────────────────────────────
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
        environment="production" if not DEBUG else "development",
    )

# ── Tiketi platform config ────────────────────────────────────────────────────
TIKETI = {
    # Vendor tiers — stake in USD cents
    "STAKE_SMALL_CENTS": 11000,         # $110.00
    "STAKE_BIG_CENTS": 22000,           # $220.00
    "STAKE_SMALL_TICKET_CAP": 1000,
    "STAKE_BIG_TICKET_CAP": None,       # unlimited

    # Revenue rates (as decimals)
    "BOOKING_FEE_RATE": 0.02,           # 2%
    "BOOKING_FEE_FLOOR_CENTS": 25,      # $0.25 minimum
    "WITHDRAWAL_FEE_RATE": 0.02,        # 2%

    # Buyback rules
    "BUYBACK_SELL_THROUGH_THRESHOLD": 0.80,
    "BUYBACK_INVENTORY_CAP": 0.15,
    "BUYBACK_MAX_PER_USER": 2,
    "BUYBACK_SINGLE_REFUND_RATE": 0.90,
    "BUYBACK_GROUP_REFUND_RATE": 0.80,

    # Relist rules
    "RELIST_PRICE_MULTIPLIER": 1.10,    # 110% of original
    "RELIST_PLATFORM_CUT": 0.40,        # 40%
    "RELIST_VENDOR_CUT": 0.60,          # 60%

    # Stake slash on vendor-caused cancellation
    "CANCEL_STAKE_SLASH_RATE": 0.15,    # 15%

    # Vendor payout
    "VENDOR_PAYOUT_LOCK_HOURS": 48,
    "ADMIN_PAYOUT_SLA_HOURS": 12,       # business hours 08:00–20:00 EAT
    "ADMIN_BUSINESS_HOURS_START": 8,
    "ADMIN_BUSINESS_HOURS_END": 20,

    # Event management
    "ADMIN_REVIEW_WINDOW_HOURS": 12,    # pause → cancel/postpone decision
    "VENDOR_REVIEW_WINDOW_HOURS": 24,   # big tier event approval
    "POSTPONE_OPT_OUT_HOURS": 48,       # fan window after postponement

    # OTP
    "OTP_VALIDITY_MINUTES": 5,
    "TOTP_VALID_WINDOW": 1,             # ±1 × 30s = ±30s tolerance

    # Group tickets
    "GROUP_SIZE_CHOICES": [2, 3, 4, 5],

    # Paystack
    "PAYSTACK_SECRET_KEY": os.environ.get("PAYSTACK_SECRET_KEY", ""),
    "PAYSTACK_PUBLIC_KEY": os.environ.get("PAYSTACK_PUBLIC_KEY", ""),
    "PAYSTACK_WEBHOOK_SECRET": os.environ.get("PAYSTACK_WEBHOOK_SECRET", ""),

    # Africa's Talking
    "AT_API_KEY": os.environ.get("AT_API_KEY", ""),
    "AT_USERNAME": os.environ.get("AT_USERNAME", "sandbox"),
    "AT_SENDER_ID": os.environ.get("AT_SENDER_ID", "TIKETI"),
}

# ── Phone number ──────────────────────────────────────────────────────────────
PHONENUMBER_DEFAULT_REGION = "KE"

# ── Debug toolbar ─────────────────────────────────────────────────────────────
INTERNAL_IPS = ["127.0.0.1"]

# ── Default primary key ───────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Logging ───────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "tiketi": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "WARNING",
            "propagate": False,
        },
    },
}

# ── Web3 / Contracts ──────────────────────────────────────────────────────────
TIKETI_CONTRACTS = {
    # Base L2 RPC (use Alchemy or Coinbase's public endpoint)
    "RPC_URL": os.environ.get("BASE_RPC_URL", "https://mainnet.base.org"),

    # Deployed contract addresses (set after deployment)
    "STAKE_ESCROW_ADDRESS":  os.environ.get("STAKE_ESCROW_ADDRESS", ""),
    "PAYOUT_VAULT_ADDRESS":  os.environ.get("PAYOUT_VAULT_ADDRESS", ""),
    "BUYBACK_POOL_ADDRESS":  os.environ.get("BUYBACK_POOL_ADDRESS", ""),

    # Platform hot wallet — signs all contract transactions
    # NEVER commit this to source control
    "PLATFORM_PRIVATE_KEY": os.environ.get("PLATFORM_PRIVATE_KEY", ""),

    # USDC on Base mainnet
    "USDC_ADDRESS": os.environ.get(
        "USDC_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    ),

    # Base Paymaster for gas sponsorship (ERC-4337)
    "PAYMASTER_URL": os.environ.get("PAYMASTER_URL", ""),

    # Minimum BuybackPool balance alert threshold (USD cents)
    "POOL_ALERT_THRESHOLD_CENTS": int(
        os.environ.get("POOL_ALERT_THRESHOLD_CENTS", "100000")  # $1,000
    ),

    # Event listener start block (set to deployment block)
    "LISTENER_START_BLOCK": int(
        os.environ.get("LISTENER_START_BLOCK", "0")
    ),
}

# ── Celery beat schedule ──────────────────────────────────────────────────────
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # void_stale_payments: every 2 minutes
    "void-stale-payments": {
        "task":     "tickets.void_stale_payments",
        "schedule": 120,  # seconds
    },
    # expire_tickets: daily at 04:00 EAT (01:00 UTC)
    "expire-tickets-daily": {
        "task":     "tickets.expire_tickets",
        "schedule": crontab(hour=1, minute=0),
    },
}
