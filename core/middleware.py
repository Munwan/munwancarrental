"""
Munwan Car Rental rate-limit middleware.

DEFAULT BEHAVIOUR
  • DEBUG=True  →  rate limiting is DISABLED (easy local development)
  • DEBUG=False →  rate limiting is ENABLED

When enabled:
  • Localhost / private IPs are exempt (127.0.0.1, ::1, 10.*, 192.168.*, 172.16-31.*)
  • Authenticated users are exempt (they already have accounts we can track)
  • Limits are per IP, per action, per rolling window
  • Always fails OPEN — if the rate-limit DB table is missing or unreachable,
    requests are allowed through so users never get blocked by infrastructure issues

Override via settings.py:
  RATE_LIMIT_ENABLED = True        # force enable even in DEBUG
  RATE_LIMIT_EXEMPT_AUTHED = False # stop exempting logged-in users
  RATE_LIMIT_BOOKING = 30          # per window
  RATE_LIMIT_LOGIN   = 10
  RATE_LIMIT_WINDOW  = 3600        # seconds
"""
import ipaddress
import logging
from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

logger = logging.getLogger('drivekenya.security')


def get_client_ip(request):
    """Extract real client IP, respecting X-Forwarded-For."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def _is_private_or_localhost(ip: str) -> bool:
    """Detect any address that means 'me' or 'my LAN'."""
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_loopback or addr.is_private or addr.is_link_local
    except ValueError:
        # Malformed IP — be permissive (not punitive)
        return True


class RateLimitMiddleware:
    """
    DB-backed rate limiter. Fails open — never blocks users if DB has issues.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._limits      = None

    def _get_limits(self):
        if self._limits is None:
            # Raised the booking limit significantly — 10/hr was trapping real
            # users who test multiple dates/vehicles before committing.
            #
            # Register is bumped to 10/hr after we added OTP — each signup attempt
            # may need a "start over" to fix a typo, hitting the limit easily.
            # /auth/verify-email/ is intentionally NOT listed — resending OTP
            # codes shouldn't count toward the registration limit; that route
            # has its own internal 60-second cooldown inside the view.
            self._limits = {
                '/booking/submit/':   ('booking', getattr(settings, 'RATE_LIMIT_BOOKING', 30)),
                '/booking/resume/':   ('booking', 30),
                '/auth/login/':       ('login',   getattr(settings, 'RATE_LIMIT_LOGIN',   10)),
                '/auth/register/':    ('register', getattr(settings, 'RATE_LIMIT_REGISTER', 10)),
                '/payments/process/': ('payment', 30),
                '/support/':          ('support', 20),
            }
        return self._limits

    def _is_enabled(self, request) -> bool:
        """Gate the whole middleware."""
        # Explicit kill switch
        if getattr(settings, 'RATE_LIMIT_ENABLED', None) is False:
            return False
        # DEBUG defaults off, unless RATE_LIMIT_ENABLED=True overrides
        if getattr(settings, 'DEBUG', False) and not getattr(settings, 'RATE_LIMIT_ENABLED', False):
            return False
        # Exempt authenticated users unless explicitly disabled
        if getattr(settings, 'RATE_LIMIT_EXEMPT_AUTHED', True):
            user = getattr(request, 'user', None)
            if user is not None and user.is_authenticated:
                return False
        return True

    def __call__(self, request):
        if request.method == 'POST' and self._is_enabled(request):
            rule = self._get_limits().get(request.path)
            if rule:
                action, limit = rule
                ip = get_client_ip(request)
                # Don't rate-limit yourself on localhost / LAN
                if not _is_private_or_localhost(ip):
                    if self._is_rate_limited(ip, action, limit):
                        logger.warning(
                            'Rate limit hit: ip=%s action=%s path=%s',
                            ip, action, request.path,
                        )
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse(
                                {'ok': False, 'error':
                                 'You\'ve made several requests in a short time. '
                                 'Please wait a minute and try again, or sign in to continue.'},
                                status=429,
                            )
                        from django.shortcuts import render
                        return render(request, 'core/429.html', status=429)
        return self.get_response(request)

    def _is_rate_limited(self, ip: str, action: str, limit: int) -> bool:
        """Increment counter; return True if limit exceeded. Always fails open."""
        try:
            from .models import RateLimitEntry
            window_seconds = getattr(settings, 'RATE_LIMIT_WINDOW', 3600)
            cutoff         = timezone.now() - timedelta(seconds=window_seconds)

            entry, created = RateLimitEntry.objects.get_or_create(
                ip_address=ip,
                action=action,
                defaults={'count': 1},
            )
            if created:
                return False

            # Reset window if expired
            if entry.window_start < cutoff:
                entry.count        = 1
                entry.window_start = timezone.now()
                entry.save(update_fields=['count', 'window_start'])
                return False

            if entry.count >= limit:
                return True

            entry.count += 1
            entry.save(update_fields=['count'])
            return False

        except Exception as exc:
            # Table missing, DB down, etc. — fail open
            logger.debug('RateLimit skipped (DB unavailable): %s', exc)
            return False