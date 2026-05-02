"""
Munwan Car Rental – Django Settings
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Load .env file ────────────────────────────────────────────────────────────
# python-dotenv reads BASE_DIR/.env into os.environ on startup. In production
# (Appliku, Heroku, etc.) the .env file is usually absent and env vars are set
# directly by the platform — this loader is a no-op in that case.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass  # dotenv not installed — env vars must come from the OS

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY','change-me-in-production-use-a-long-random-string-50chars+')
DEBUG        = os.environ.get('DEBUG', 'True') == 'True'

# ALLOWED_HOSTS: tolerant of comma, space, or mixed separators in .env.
# Examples that all work:
#   ALLOWED_HOSTS=localhost,127.0.0.1,munwancarrental.com
#   ALLOWED_HOSTS=localhost 127.0.0.1 munwancarrental.com
#   ALLOWED_HOSTS=localhost, 127.0.0.1, munwancarrental.com
import re as _re
_raw_hosts = os.environ.get(
    'ALLOWED_HOSTS',
    'localhost 127.0.0.1 munwancarrental.com www.munwancarrental.com'
)
ALLOWED_HOSTS = [h.strip() for h in _re.split(r'[,\s;]+', _raw_hosts) if h.strip()]

INSTALLED_APPS = [
    'django.contrib.admin','django.contrib.auth','django.contrib.contenttypes',
    'django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.RateLimitMiddleware',
]

ROOT_URLCONF = 'drivekenya.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

WSGI_APPLICATION = 'drivekenya.wsgi.application'

# ── DATABASE ──────────────────────────────────────────────────────────────────
# If DATABASE_URL is set in .env, use it (PostgreSQL on Appliku/Hetzner).
# Otherwise fall back to local SQLite for quick dev work.
_db_url = os.environ.get('DATABASE_URL', '').strip()
if _db_url:
    # Parse: postgres://user:pass@host:port/dbname
    from urllib.parse import urlparse
    _u = urlparse(_db_url)
    DATABASES = {
        'default': {
            'ENGINE':   'django.db.backends.postgresql',
            'NAME':     _u.path.lstrip('/'),
            'USER':     _u.username,
            'PASSWORD': _u.password,
            'HOST':     _u.hostname,
            'PORT':     _u.port or 5432,
            'CONN_MAX_AGE': 60,
            'OPTIONS':  {'sslmode': os.environ.get('DB_SSLMODE', 'prefer')},
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME':   BASE_DIR / 'db.sqlite3',
        }
    }

# Custom auth: allow login with email OR username.
AUTHENTICATION_BACKENDS = [
    'core.auth_backends.EmailOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Django 5+ STORAGES — WhiteNoise compressed-manifest for static, default for media.
# Enables long-lived cache headers + automatic gzip/brotli for /static/.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── EMAIL ─────────────────────────────────────────────────────────────────────
# If EMAIL_HOST is set in .env, use real SMTP. Otherwise console (dev only).
if os.environ.get('EMAIL_HOST'):
    EMAIL_BACKEND     = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST        = os.environ.get('EMAIL_HOST')
    EMAIL_PORT        = int(os.environ.get('EMAIL_PORT', 587))
    EMAIL_USE_TLS     = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
    EMAIL_USE_SSL     = os.environ.get('EMAIL_USE_SSL', 'False').lower() == 'true'
    EMAIL_HOST_USER   = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
    EMAIL_TIMEOUT     = 20
else:
    EMAIL_BACKEND     = 'django.core.mail.backends.console.EmailBackend'

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Munwan Car Rental <info@munwancarrental.com>')
ADMIN_BOOKING_EMAIL = os.environ.get('ADMIN_BOOKING_EMAIL', 'info@munwancarrental.com')

# ── Paystack ──────────────────────────────────────────────────────────────────
# Get from: https://dashboard.paystack.com/#/settings/developers
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', 'pk_test_REPLACE_ME')
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', 'sk_test_REPLACE_ME')

# ── PayPal ────────────────────────────────────────────────────────────────────
PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID', 'REPLACE_ME')
PAYPAL_SECRET    = os.environ.get('PAYPAL_SECRET',    'REPLACE_ME')
PAYPAL_MODE      = os.environ.get('PAYPAL_MODE',      'sandbox')

# ── M-Pesa ────────────────────────────────────────────────────────────────────
MPESA_CONSUMER_KEY    = os.environ.get('MPESA_CONSUMER_KEY',    'REPLACE_ME')
MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET', 'REPLACE_ME')
MPESA_SHORTCODE       = os.environ.get('MPESA_SHORTCODE',       '174379')
MPESA_PASSKEY         = os.environ.get('MPESA_PASSKEY',         'REPLACE_ME')
MPESA_CALLBACK_URL    = os.environ.get('MPESA_CALLBACK_URL',    'https://yourdomain.com/payments/mpesa/callback/')
MPESA_ENV             = os.environ.get('MPESA_ENV',             'sandbox')

# ── Site config ───────────────────────────────────────────────────────────────
WHATSAPP_NUMBER = os.environ.get('WHATSAPP_NUMBER', '254727745907')
SITE_URL        = os.environ.get('SITE_URL', 'https://yourdomain.com')

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_BOOKING = 10
RATE_LIMIT_LOGIN   = 5
RATE_LIMIT_WINDOW  = 3600

if not DEBUG:
    # HTTPS
    SECURE_SSL_REDIRECT            = True
    SECURE_PROXY_SSL_HEADER        = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS            = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD            = True
    # Cookies
    SESSION_COOKIE_SECURE          = True
    CSRF_COOKIE_SECURE             = True
    SESSION_COOKIE_HTTPONLY        = True
    CSRF_COOKIE_HTTPONLY           = False  # must be False if JS reads the token
    SESSION_COOKIE_SAMESITE        = 'Lax'
    CSRF_COOKIE_SAMESITE           = 'Lax'
    # Content
    SECURE_BROWSER_XSS_FILTER      = True
    SECURE_CONTENT_TYPE_NOSNIFF    = True
    X_FRAME_OPTIONS                = 'DENY'
    SECURE_REFERRER_POLICY         = 'strict-origin-when-cross-origin'
    # Sessions: 14-day expiry, refreshed on activity. Cookie age 24h.
    SESSION_EXPIRE_AT_BROWSER_CLOSE = False
    SESSION_COOKIE_AGE              = 60 * 60 * 24 * 14   # 14 days
    SESSION_SAVE_EVERY_REQUEST      = True                 # rolling expiry
    # Trust the X-Forwarded-* headers from Cloudflare/Hetzner proxy only
    USE_X_FORWARDED_HOST            = True

# CSRF trusted origins — required in Django 4+ for HTTPS POSTs from your domain.
# Pulled from env so dev/prod can differ. Format: comma-separated full origins.
_csrf_origins = os.environ.get(
    'CSRF_TRUSTED_ORIGINS',
    'https://munwancarrental.com,https://www.munwancarrental.com'
).strip()
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(',') if o.strip()]

# ADMINS get emailed on 500 errors (when EMAIL_HOST is configured)
_admin_email_for_errors = os.environ.get('ADMIN_BOOKING_EMAIL', 'info@munwancarrental.com')
ADMINS = [('Munwan Admin', _admin_email_for_errors)]
SERVER_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', _admin_email_for_errors)

# Logging — explicit config so logs go to stderr (Appliku captures these)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
            'include_html': True,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'mail_admins'] if not DEBUG else ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'mail_admins'] if not DEBUG else ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'drivekenya': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}