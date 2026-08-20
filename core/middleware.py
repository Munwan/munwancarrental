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
  RATE_LIMIT_CHECK_BOOKING = 20    # GET /booking/check/ — reference lookup
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
    """
    Extract the real client IP.

    Caddy's reverse_proxy block (Caddyfile) sets X-Real-IP to the actual
    connecting address on every request, overwriting anything the client
    sent — that's the only header we trust as authoritative.

    X-Forwarded-For is NOT used as a fallback here: Caddy appends to that
    header rather than replacing it, so a client that sends its own fake
    X-Forwarded-For ends up as the FIRST entry — naive `.split(',')[0]`
    parsing (the previous implementation) returns the attacker-controlled
    value instead of the real IP Caddy appended, silently defeating every
    IP-keyed rate limit in RateLimitMiddleware.
    """
    real_ip = request.META.get('HTTP_X_REAL_IP')
    if real_ip:
        return real_ip.strip()
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
                ('POST', '/booking/submit/'):   ('booking', getattr(settings, 'RATE_LIMIT_BOOKING', 30)),
                ('POST', '/booking/resume/'):   ('booking', 30),
                ('POST', '/auth/login/'):       ('login',   getattr(settings, 'RATE_LIMIT_LOGIN',   10)),
                ('POST', '/auth/register/'):    ('register', getattr(settings, 'RATE_LIMIT_REGISTER', 10)),
                ('POST', '/payments/process/'): ('payment', 30),
                ('POST', '/support/'):          ('support', 20),
                # GET — both are ownership-check-free public reference
                # lookups (by design — "check my booking" / resume payment),
                # so without a limit here each is an unthrottled oracle for
                # enumerating other customers' trip details.
                ('GET', '/booking/check/'):     ('check_booking', getattr(settings, 'RATE_LIMIT_CHECK_BOOKING', 20)),
                ('GET', '/booking/summary/'):   ('check_booking', getattr(settings, 'RATE_LIMIT_CHECK_BOOKING', 20)),
                # Django admin has no brute-force protection of its own
                # (unlike /auth/login/'s 5-fails/15-min lockout) — same
                # login action/limit as the customer-facing login.
                ('POST', '/admin/login/'):      ('login', getattr(settings, 'RATE_LIMIT_LOGIN', 10)),
            }
        return self._limits

    # Prefix-matched rules for paths with a dynamic segment (e.g. the
    # booking reference in /invoice/<ref>/), checked when no exact match
    # is found. Same enumeration concern as /booking/check/ — invoice
    # references are also just 6 random hex chars, and this endpoint
    # reveals company name, KRA PIN, and billing totals.
    def _prefix_limits(self):
        return [
            ('GET', '/invoice/', 'check_booking', getattr(settings, 'RATE_LIMIT_CHECK_BOOKING', 20)),
        ]

    # Actions that stay rate-limited even for authenticated users. Signing up
    # only costs an email + OTP round-trip, so "authenticated" isn't a real
    # barrier against someone using an account purely to dodge the
    # enumeration limit on the reference-lookup endpoints above.
    _NO_AUTH_EXEMPT = {'check_booking'}

    def _is_enabled(self, request) -> bool:
        """Gate the whole middleware (kill switch / DEBUG only — auth
        exemption is handled per-rule in __call__, since a couple of rules
        must still apply to authenticated users)."""
        # Explicit kill switch
        if getattr(settings, 'RATE_LIMIT_ENABLED', None) is False:
            return False
        # DEBUG defaults off, unless RATE_LIMIT_ENABLED=True overrides
        if getattr(settings, 'DEBUG', False) and not getattr(settings, 'RATE_LIMIT_ENABLED', False):
            return False
        return True

    def _is_authed_exempt(self, request) -> bool:
        if not getattr(settings, 'RATE_LIMIT_EXEMPT_AUTHED', True):
            return False
        user = getattr(request, 'user', None)
        return bool(user is not None and user.is_authenticated)

    def __call__(self, request):
        if self._is_enabled(request):
            rule = self._get_limits().get((request.method, request.path))
            if rule is None:
                for method, prefix, action, limit in self._prefix_limits():
                    if request.method == method and request.path.startswith(prefix):
                        rule = (action, limit)
                        break
            if rule:
                action, limit = rule
                if action not in self._NO_AUTH_EXEMPT and self._is_authed_exempt(request):
                    return self.get_response(request)
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