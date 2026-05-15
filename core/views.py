import json
import logging
import secrets
import traceback
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .emails import send_booking_confirmation, send_support_notification, send_otp_email
from .forms import (
    BookingStep1Form, BookingPaymentForm,
    CheckBookingForm, LoginForm, RegisterForm, SupportForm,
)
from .middleware import get_client_ip
from .models import (Booking, EmailOTP, PaymentLog, Review, SafariDestination,
                     SafariPricing, SupportTicket, Vehicle, make_invoice_number)
from .payments import PaystackBackend, MpesaBackend, PayPalBackend

# Module-level alias so booking_submit can call it with underscore prefix
# (keeping the public name in models.py clean while marking internal use here).
_make_invoice_number = make_invoice_number

logger = logging.getLogger('drivekenya.views')


# ── Email OTP constants ──────────────────────────────────────────
OTP_EXPIRY_MINUTES = 15
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60


def _generate_otp_code() -> str:
    """Cryptographically random 6-digit numeric code."""
    return f'{secrets.randbelow(1_000_000):06d}'


def _create_and_send_otp(user):
    """
    Invalidate any prior unverified OTPs for this email, create a fresh one,
    and email it to the user.
    """
    EmailOTP.objects.filter(email__iexact=user.email, verified_at__isnull=True).delete()
    code = _generate_otp_code()
    expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    otp = EmailOTP.objects.create(
        email=user.email, code=code, user=user, expires_at=expires_at,
    )
    try:
        send_otp_email(to_email=user.email, code=code, first_name=user.first_name or '')
    except Exception as exc:
        logger.exception('OTP email send failed for %s', user.email)
    return otp


def _json_error(message, status=400):
    return JsonResponse({'ok': False, 'error': message}, status=status)


def _fire_email(fn, *args, **kwargs):
    """
    Run an email-send function in a daemon thread that LOGS its own
    exceptions. Plain `threading.Thread(target=fn).start()` swallows
    exceptions silently — making "email never arrived" bugs invisible.

    Usage:
        _fire_email(send_booking_confirmation, booking)
    """
    import threading

    def _runner():
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception('Email thread failed: %s', getattr(fn, '__name__', str(fn)))

    threading.Thread(target=_runner, daemon=True).start()


# ─────────────────────────────────────────────────────────────
#  HOME
# ─────────────────────────────────────────────────────────────
def home(request):
    try:
        vehicles = list(Vehicle.objects.filter(is_available=True))
    except Exception:
        vehicles = []
    try:
        reviews = list(Review.objects.filter(is_published=True)[:6])
    except Exception:
        reviews = []

    # Airport-transfer pricing constants for the JS to use client-side.
    # Server is still source of truth — this is only for instant preview.
    try:
        from .airport_transfer import dump_js_constants
        transfer_constants_json = dump_js_constants()
    except Exception:
        transfer_constants_json = '{}'

    context = {
        'vehicles':           vehicles,
        'reviews':            reviews,
        'paystack_pk':        getattr(settings, 'PAYSTACK_PUBLIC_KEY', ''),
        'paypal_client_id':   getattr(settings, 'PAYPAL_CLIENT_ID', ''),
        'whatsapp_number':    getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
        'pickup_choices':     Booking.PICKUP_LOCATION_CHOICES,
        'transfer_constants_json': transfer_constants_json,
    }
    return render(request, 'core/home.html', context)


# ─────────────────────────────────────────────────────────────
#  STATIC INFO PAGES
# ─────────────────────────────────────────────────────────────
def faqs(request):
    return render(request, 'core/faqs.html', {
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    })


def cancellation(request):
    return render(request, 'core/cancellation.html', {
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    })


def terms(request):
    """Terms & Conditions page."""
    return render(request, 'core/terms.html', {
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    })


def privacy(request):
    """Privacy Policy page."""
    return render(request, 'core/privacy.html', {
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    })


# ─────────────────────────────────────────────────────────────
#  SAFARI — quote endpoint & destination list
# ─────────────────────────────────────────────────────────────
def safari_destinations(request):
    """
    Returns the list of active safari destinations for the booking form.
    Public, GET only, cached at the CDN edge for speed (small payload).
    """
    dests = SafariDestination.objects.filter(is_active=True).order_by('order', 'name')
    return JsonResponse({
        'ok': True,
        'destinations': [
            {
                'id':           d.id,
                'name':         d.name,
                'short_name':   d.short_name,
                'slug':         d.slug,
                'description':  d.description,
                'distance_km':  d.distance_km,
                'days':         max(d.recommended_days, d.min_days),
                'min_days':     d.min_days,
            }
            for d in dests
        ],
    })


@require_POST
def safari_quote(request):
    """
    Returns a live quote for a safari given:
      vehicle_id: int
      destinations: comma-separated SafariDestination IDs (e.g. "3,1,7")
    Optional:
      days_override: dict-like form data with days_<destid> overrides

    Response shape matches what the JS price preview expects:
      { ok, total_usd, total_kes, total_eur, breakdown: [{name, days, daily_usd, subtotal_usd}] }

    Pricing logic: for each chosen destination, look up SafariPricing for
    that (destination, vehicle); use the per-day rate × days. Days defaults
    to destination.recommended_days but can be overridden per leg via form.
    """
    from decimal import Decimal
    try:
        vehicle_id = int(request.POST.get('vehicle_id') or 0)
    except ValueError:
        return _json_error('Invalid vehicle.', 400)

    dest_ids_raw = (request.POST.get('destinations') or '').strip()
    if not dest_ids_raw:
        return _json_error('Pick at least one safari destination.', 400)
    try:
        dest_ids = [int(x) for x in dest_ids_raw.split(',') if x.strip()]
    except ValueError:
        return _json_error('Invalid destination IDs.', 400)

    try:
        vehicle = Vehicle.objects.get(id=vehicle_id, category='safari', is_available=True)
    except Vehicle.DoesNotExist:
        return _json_error('Vehicle is not safari-ready or unavailable.', 404)

    # Preserve the order the customer picked the destinations.
    dests = list(SafariDestination.objects.filter(id__in=dest_ids, is_active=True))
    dests_by_id = {d.id: d for d in dests}
    ordered = [dests_by_id[i] for i in dest_ids if i in dests_by_id]
    if not ordered:
        return _json_error('Destinations not found or inactive.', 404)

    # Build the breakdown
    breakdown = []
    total_usd = Decimal('0')
    KES_PER_USD = Decimal('130')
    EUR_PER_USD = Decimal('0.93')

    for d in ordered:
        try:
            cell = SafariPricing.objects.get(destination=d, vehicle=vehicle)
            daily = cell.price_usd
        except SafariPricing.DoesNotExist:
            # No price set for this combination — fall back to vehicle's
            # base daily rate. Admin should fill this in but we don't want
            # to silently exclude the destination.
            daily = vehicle.price_usd

        # Per-destination day override (e.g. "days_3=2" for destination 3)
        days_key = f'days_{d.id}'
        try:
            days = int(request.POST.get(days_key) or d.recommended_days)
        except ValueError:
            days = d.recommended_days
        # Enforce destination min based on driving distance from Nairobi.
        # Customer cannot book fewer days than is physically possible for a
        # round trip — e.g. Samburu (350km) needs minimum 3 days.
        days = max(d.min_days, min(days, 14))

        subtotal = (daily * Decimal(days)).quantize(Decimal('0.01'))
        total_usd += subtotal
        breakdown.append({
            'destination_id': d.id,
            'name':           d.short_name,
            'days':           days,
            'daily_usd':      float(daily),
            'subtotal_usd':   float(subtotal),
        })

    total_kes = (total_usd * KES_PER_USD).quantize(Decimal('1'))
    total_eur = (total_usd * EUR_PER_USD).quantize(Decimal('0.01'))

    return JsonResponse({
        'ok':           True,
        'vehicle_id':   vehicle.id,
        'vehicle_name': vehicle.name,
        'total_usd':    float(total_usd),
        'total_kes':    int(total_kes),
        'total_eur':    float(total_eur),
        'total_days':   sum(b['days'] for b in breakdown),
        'breakdown':    breakdown,
    })


@require_POST
def _booking_submit_safari(request):
    """
    Handle a Safari Package booking. Customer picks one or more destinations
    (sequential trip). Total = sum over (vehicle_daily_at_destination × days).
    Driver is always included; no return_date concept (pickup_date + total_days).
    """
    from datetime import datetime, timedelta
    from decimal import Decimal

    P = request.POST
    errors = {}

    def _grab(key, label, max_len=200):
        v = (P.get(key) or '').strip()
        if not v:
            errors[key] = f'{label} is required.'
        return v[:max_len]

    first_name  = _grab('first_name', 'First name', 60)
    last_name   = _grab('last_name',  'Last name',  60)
    email       = _grab('email',      'Email')
    phone       = _grab('phone',      'Phone')
    nationality = (P.get('nationality') or 'Kenya').strip()[:60]

    # Vehicle: must be safari-ready
    try:
        vehicle_id = int(P.get('vehicle') or 0)
        vehicle    = Vehicle.objects.get(id=vehicle_id, category='safari', is_available=True)
    except (ValueError, Vehicle.DoesNotExist):
        errors['vehicle'] = 'Pick a safari-ready vehicle.'
        vehicle = None

    # Destinations: comma-separated IDs
    dest_ids_raw = (P.get('safari_destinations') or '').strip()
    dest_ids = []
    if dest_ids_raw:
        try:
            dest_ids = [int(x) for x in dest_ids_raw.split(',') if x.strip()]
        except ValueError:
            errors['safari_destinations'] = 'Invalid destination IDs.'
    if not dest_ids:
        errors['safari_destinations'] = 'Pick at least one safari destination.'

    pickup_date_str  = _grab('pickup_date', 'Pickup date')
    pickup_time_str  = (P.get('pickup_time') or '08:00').strip()
    pickup_location  = (P.get('pickup_location') or 'JKIA').strip()

    # Email + phone validation
    import re as _re
    if email and ('@' not in email or '.' not in email or email.endswith('@')):
        errors['email'] = 'Please enter a valid email address.'
    if phone and not _re.match(r'^\+?[\d\s\-\(\)]{7,20}$', phone):
        errors['phone'] = 'Enter a valid phone number.'

    if not P.get('terms_accepted'):
        errors['terms_accepted'] = 'Please accept the Terms & Cancellation Policy.'

    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    # Parse pickup
    try:
        pickup_date = datetime.strptime(pickup_date_str, '%Y-%m-%d').date()
        pickup_time = datetime.strptime(pickup_time_str, '%H:%M').time()
    except ValueError:
        return JsonResponse({'ok': False, 'errors': {
            'pickup_date': 'Invalid date or time.'
        }}, status=400)

    # Reject same-day and past dates
    from django.utils import timezone as _tz
    tomorrow = _tz.localdate() + timedelta(days=1)
    if pickup_date < tomorrow:
        return JsonResponse({'ok': False, 'errors': {
            'safari_pickup_date': 'Safari start date must be tomorrow or later. WhatsApp us for urgent bookings.'
        }}, status=400)

    # Resolve destinations (preserving customer's order)
    dests_by_id = {d.id: d for d in SafariDestination.objects.filter(
        id__in=dest_ids, is_active=True)}
    ordered = [dests_by_id[i] for i in dest_ids if i in dests_by_id]
    if not ordered:
        return JsonResponse({'ok': False, 'errors': {
            'safari_destinations': 'Destinations not found.'
        }}, status=400)

    # Compute price (server is source of truth, mirrors safari_quote)
    breakdown = []
    total_usd = Decimal('0')
    KES_PER_USD = Decimal('130')
    EUR_PER_USD = Decimal('0.93')

    for d in ordered:
        try:
            daily = SafariPricing.objects.get(destination=d, vehicle=vehicle).price_usd
        except SafariPricing.DoesNotExist:
            daily = vehicle.price_usd

        try:
            days = int(P.get(f'days_{d.id}') or d.recommended_days)
        except ValueError:
            days = d.recommended_days
        # Same min-days enforcement as safari_quote — keep the two paths
        # in sync or customers will see different totals between preview and submit.
        days = max(d.min_days, min(days, 14))

        subtotal = (daily * Decimal(days)).quantize(Decimal('0.01'))
        total_usd += subtotal
        breakdown.append({
            'destination_id': d.id,
            'name':           d.short_name,
            'days':           days,
            'daily_usd':      float(daily),
            'subtotal_usd':   float(subtotal),
        })

    total_days  = sum(b['days'] for b in breakdown)
    return_date = pickup_date + timedelta(days=total_days)
    total_kes   = (total_usd * KES_PER_USD).quantize(Decimal('1'))
    total_eur   = (total_usd * EUR_PER_USD).quantize(Decimal('0.01'))

    # ── Edit-instead-of-duplicate (mirrors transfer flow) ────
    booking = None
    existing_ref = (P.get('edit_ref') or '').strip()
    if existing_ref:
        try:
            booking = Booking.objects.get(
                reference=existing_ref,
                payment_status='unpaid',
                email__iexact=email.lower(),
            )
        except Booking.DoesNotExist:
            booking = None

    if booking is None:
        booking = Booking(
            ip_address = get_client_ip(request),
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500],
        )

    booking.first_name  = first_name
    booking.last_name   = last_name
    booking.email       = email.lower()
    booking.phone       = phone
    booking.nationality = nationality
    booking.vehicle     = vehicle
    booking.hire_type   = 'safari'
    booking.with_driver = True    # safari always includes driver
    booking.baby_seat   = False
    booking.pickup_location  = pickup_location
    booking.pickup_date      = pickup_date
    booking.pickup_time      = pickup_time
    booking.return_date      = return_date
    booking.return_time      = pickup_time
    booking.days             = total_days
    booking.base_price_usd   = total_usd
    booking.driver_fee_usd   = Decimal('0.00')   # driver baked into daily
    booking.total_usd        = total_usd
    booking.total_kes        = total_kes
    booking.total_eur        = total_eur
    booking.terms_accepted   = bool(P.get('terms_accepted'))
    booking.safari_breakdown = breakdown

    if request.user.is_authenticated:
        booking.user = request.user
    booking.save()
    # M2M can only be set after the booking has a PK
    booking.safari_destinations.set([d.id for d in ordered])

    request.session['pending_booking_id'] = booking.id

    # Account creation (matches rental/transfer flow)
    account_created = False
    if P.get('create_account') == 'on' and P.get('password'):
        existing = User.objects.filter(email__iexact=email.lower()).first()
        if existing and request.user.is_authenticated and request.user == existing:
            booking.user = existing
            booking.save(update_fields=['user'])
        elif not existing:
            try:
                new_user = User.objects.create_user(
                    username=email.lower(), email=email.lower(),
                    password=P.get('password'),
                    first_name=first_name, last_name=last_name,
                )
                new_user.is_active = False
                new_user.save(update_fields=['is_active'])
                booking.user = new_user
                booking.save(update_fields=['user'])
                try:
                    _create_and_send_otp(new_user)
                    request.session['otp_user_pk'] = new_user.pk
                except Exception:
                    logger.exception('Safari-flow OTP send failed for %s', email)
                account_created = True
            except Exception:
                logger.exception('Safari-flow account creation failed')

    # Fire customer + admin emails in background
    try:
        from .emails import send_new_booking_admin_alert, send_booking_received
        _fire_email(send_new_booking_admin_alert, booking)
        _fire_email(send_booking_received, booking)
    except Exception:
        logger.exception('Safari booking email threads failed')

    return JsonResponse({
        'ok':             True,
        'reference':      booking.reference,
        'total_usd':      float(booking.total_usd),
        'total_kes':      int(booking.total_kes),
        'total_eur':      float(booking.total_eur),
        'vehicle_name':   vehicle.name,
        'total_days':     total_days,
        'breakdown':      breakdown,
        'is_safari':      True,
        'account_created': account_created,
    })


# ─────────────────────────────────────────────────────────────
#  BOOKING SUBMIT  (Step 1)
# ─────────────────────────────────────────────────────────────
@require_POST
def _booking_submit_transfer(request):
    """
    Handle an Airport Transfer booking. Different shape from rental:
    - No return_date / return_time
    - No days field (single trip)
    - Price comes from airport_transfer.quote() based on zone + car type
    - Vehicle is auto-assigned from the chosen transfer_car_type
    """
    from .airport_transfer import detect_zone, is_night_pickup, quote, KES_PER_USD

    # ── Field extraction with light validation ───────────────
    P = request.POST
    errors = {}
    def _grab(key, label, max_len=200):
        v = (P.get(key) or '').strip()
        if not v:
            errors[key] = f'{label} is required.'
        return v[:max_len]

    first_name = _grab('first_name', 'First name', 60)
    last_name  = _grab('last_name',  'Last name',  60)
    email      = _grab('email',      'Email')
    phone      = _grab('phone',      'Phone')
    nationality = (P.get('nationality') or 'Kenya').strip()[:60]

    direction  = (P.get('transfer_direction') or 'FROM').strip().upper()
    if direction not in ('FROM', 'TO'):
        errors['transfer_direction'] = 'Pick a transfer direction.'

    car_type = (P.get('transfer_car_type') or '').strip().lower()
    if car_type not in ('economy', 'midsize', 'luxury', 'van'):
        errors['transfer_car_type'] = 'Pick a car type.'

    location_raw = _grab('transfer_location', 'Location', 120)
    zone = detect_zone(location_raw) if location_raw else ''
    if not zone:
        errors['transfer_location'] = 'Pick a location from the list — we couldn\'t detect the zone.'

    pickup_date_str = _grab('transfer_pickup_date', 'Pickup date')
    pickup_time_str = _grab('transfer_pickup_time', 'Pickup time')

    # Email format check (mirrors the JS-side rule)
    if email and ('@' not in email or '.' not in email or email.endswith('@')):
        errors['email'] = 'Please enter a valid email address (must contain @ and . — e.g. you@example.com).'

    # Phone format check (same regex used by rental flow's clean_phone).
    # Allows international format: optional leading +, 7-20 digits/spaces/dashes.
    import re as _re
    if phone and not _re.match(r'^\+?[\d\s\-\(\)]{7,20}$', phone):
        errors['phone'] = 'Enter a valid phone number (e.g. +254 7XX XXX XXX).'

    # Terms must be accepted (matches rental flow)
    if not P.get('terms_accepted'):
        errors['terms_accepted'] = 'Please accept the Terms & Cancellation Policy.'

    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    # ── Parse date/time ──────────────────────────────────────
    try:
        from datetime import datetime, timedelta as _td
        pickup_date = datetime.strptime(pickup_date_str, '%Y-%m-%d').date()
        pickup_time = datetime.strptime(pickup_time_str, '%H:%M').time()
    except ValueError:
        return JsonResponse({'ok': False, 'errors': {
            'transfer_pickup_date': 'Invalid date or time.'
        }}, status=400)

    # Reject same-day and past dates (we need at least 1 day to confirm)
    from django.utils import timezone as _tz
    tomorrow = _tz.localdate() + _td(days=1)
    if pickup_date < tomorrow:
        return JsonResponse({'ok': False, 'errors': {
            'transfer_pickup_date': 'Pickup must be tomorrow or later. WhatsApp us for urgent transfers.'
        }}, status=400)

    # ── Pick a vehicle of the right type ─────────────────────
    candidate = (Vehicle.objects
                 .filter(is_available=True, transfer_car_type=car_type)
                 .order_by('order', 'name')
                 .first())
    if not candidate:
        return JsonResponse({'ok': False, 'errors': {
            'transfer_car_type': f'No {car_type} vehicle currently available. Try a different car type.'
        }}, status=400)

    # ── Compute price (server is source of truth) ───────────
    q = quote(zone, car_type, pickup_time)
    if not q.get('ok'):
        return JsonResponse({'ok': False, 'errors': {
            'transfer_location': q.get('error', 'Could not compute price.')
        }}, status=400)

    # ── Edit-instead-of-duplicate ────────────────────────────
    # If the form supplies edit_ref AND that booking is still unpaid AND
    # the email matches, update the existing booking. Stops the customer
    # from creating duplicates by going Back → Edit → Continue.
    from decimal import Decimal
    booking = None
    existing_ref = (P.get('edit_ref') or '').strip()
    if existing_ref:
        try:
            booking = Booking.objects.get(
                reference=existing_ref,
                payment_status='unpaid',
                email__iexact=email.lower(),  # only the original booker can edit
            )
        except Booking.DoesNotExist:
            booking = None  # fall through to create-new

    if booking is None:
        booking = Booking(
            ip_address  = get_client_ip(request),
            user_agent  = request.META.get('HTTP_USER_AGENT', '')[:500],
        )

    # ── Apply form data (works for both create and update paths) ────
    booking.first_name  = first_name
    booking.last_name   = last_name
    booking.email       = email.lower()
    booking.phone       = phone
    booking.nationality = nationality
    booking.vehicle     = candidate
    booking.hire_type   = 'transfer'
    booking.with_driver = True
    booking.baby_seat   = False
    booking.pickup_location  = 'JKIA' if direction == 'FROM' else 'other'
    booking.hotel_address    = location_raw if direction == 'TO' else ''
    booking.dropoff_location = location_raw if direction == 'FROM' else 'JKIA'
    booking.pickup_date      = pickup_date
    booking.pickup_time      = pickup_time
    booking.return_date      = None
    booking.return_time      = None
    booking.transfer_direction   = direction
    booking.transfer_zone        = zone
    booking.transfer_car_type    = car_type
    booking.transfer_destination = (P.get('transfer_destination_text') or '').strip()[:120]
    booking.is_night_surcharge   = q['night']
    booking.days            = 1
    booking.base_price_usd  = Decimal(str(q['usd_total']))
    booking.driver_fee_usd  = Decimal('0.00')
    booking.total_usd       = Decimal(str(q['usd_total']))
    booking.total_kes       = Decimal(str(q['kes_total']))
    booking.total_eur       = Decimal(str(q['eur_total']))
    booking.terms_accepted  = bool(P.get('terms_accepted'))

    if request.user.is_authenticated:
        booking.user = request.user
    booking.save()

    # CRITICAL: store pending_booking_id in session so /payments/process/
    # can find this booking later. Without this, customer pays via Paystack
    # but the callback's session lookup fails → "Session expired" + booking
    # stays unpaid even though money was charged.
    request.session['pending_booking_id'] = booking.id

    # ── Optional account creation (mirrors rental flow) ───────
    # New accounts created here are inactive until OTP-verified.
    # Booking is already saved — account creation is a side effect.
    account_created = False
    if (P.get('create_account') == 'on' and P.get('password')):
        existing = User.objects.filter(email__iexact=email.lower()).first()
        if existing:
            if request.user.is_authenticated and request.user == existing:
                booking.user = existing
                booking.save(update_fields=['user'])
        else:
            try:
                new_user = User.objects.create_user(
                    username   = email.lower(),
                    email      = email.lower(),
                    password   = P.get('password'),
                    first_name = first_name,
                    last_name  = last_name,
                )
                new_user.is_active = False
                new_user.save(update_fields=['is_active'])
                booking.user = new_user
                booking.save(update_fields=['user'])
                try:
                    _create_and_send_otp(new_user)
                    request.session['otp_user_pk'] = new_user.pk
                except Exception as otp_exc:
                    logger.exception('Transfer-flow OTP send failed for %s', email)
                account_created = True
            except Exception as exc:
                logger.exception('Transfer-flow account creation failed')

    # Admin alert + customer "booking received" email
    try:
        from .emails import send_new_booking_admin_alert, send_booking_received
        _fire_email(send_new_booking_admin_alert, booking)
        _fire_email(send_booking_received, booking)
    except Exception as e:
        logger.exception('Transfer booking email threads failed')

    return JsonResponse({
        'ok':                True,
        'reference':         booking.reference,
        'total_usd':         float(booking.total_usd),
        'total_kes':         q['kes_total'],
        'total_eur':         q['eur_total'],
        'is_transfer':       True,
        'zone_label':        booking.get_transfer_zone_display(),
        'car_type_label':    booking.get_transfer_car_type_display(),
        'vehicle_name':      candidate.name,
        'night_surcharge':   q['night'],
        'account_created':   account_created,
    })


# ─────────────────────────────────────────────────────────────
#  BOOKING — STEP 1 (validate + save reservation)
# ─────────────────────────────────────────────────────────────
@require_POST
def booking_submit(request):
    try:
        hire_type = (request.POST.get('hire_type') or '').strip()
        # ── Branch: Airport Transfer bookings have a different field set,
        # so they go through their own validation/save path.
        if hire_type == 'transfer':
            return _booking_submit_transfer(request)
        # ── Branch: Safari Package bookings let the customer pick 1+
        # destinations; pricing is computed from SafariPricing rows.
        if hire_type == 'safari':
            return _booking_submit_safari(request)

        form = BookingStep1Form(request.POST)
        if not form.is_valid():
            errors = {k: v[0] if isinstance(v, list) else str(v)
                      for k, v in form.errors.items()}
            return JsonResponse({'ok': False, 'errors': errors}, status=400)

        cd          = form.cleaned_data
        vehicle     = cd['vehicle']
        pickup_date = cd['pickup_date']
        return_date = cd['return_date']
        days        = (return_date - pickup_date).days or 1

        with_driver = bool(cd.get('with_driver', False))
        baby_seat   = bool(cd.get('baby_seat', False))

        # ── Edit-instead-of-duplicate ──
        # If the form includes ?edit_ref=<reference> and that booking is still
        # unpaid, update it. Stops Back→Continue from creating duplicates.
        existing_ref = (request.POST.get('edit_ref') or '').strip()
        booking = None
        is_meaningful_edit = False  # set to True if price-affecting fields changed
        if existing_ref:
            try:
                booking = Booking.objects.get(
                    reference=existing_ref,
                    payment_status='unpaid',
                    email__iexact=cd['email'],  # only the owner can edit
                )
                # Detect if the edit changes anything that affects the total.
                # If so, the customer effectively has a "new" booking and we
                # need to reset the reminder window so the email reflects the
                # latest price.
                if (
                    booking.vehicle_id != vehicle.id
                    or booking.days != days
                    or booking.with_driver != with_driver
                    or booking.baby_seat != baby_seat
                    or booking.hire_type != cd['hire_type']
                ):
                    is_meaningful_edit = True
            except Booking.DoesNotExist:
                booking = None  # fall through to create-new

        if booking is None:
            booking = Booking(
                ip_address    = get_client_ip(request),
                user_agent    = request.META.get('HTTP_USER_AGENT', '')[:500],
            )

        # Apply form data — works for both create and update paths
        booking.first_name       = cd['first_name']
        booking.last_name        = cd['last_name']
        booking.email            = cd['email']
        booking.phone            = cd['phone']
        booking.nationality      = cd['nationality']
        booking.vehicle          = vehicle
        booking.hire_type        = cd['hire_type']
        # Safari Package always includes a driver — enforce server-side
        # in case the customer manipulated the form to send self-drive.
        booking.with_driver      = True if cd['hire_type'] == 'safari' else with_driver
        booking.baby_seat        = baby_seat
        booking.pickup_location  = cd['pickup_location']
        booking.hotel_address    = cd.get('hotel_address') or ''
        booking.dropoff_location = cd.get('dropoff_location') or ''
        booking.pickup_date      = pickup_date
        booking.pickup_time      = cd['pickup_time']
        booking.return_date      = return_date
        booking.return_time      = cd['return_time']
        booking.days             = days
        booking.base_price_usd   = 0
        booking.driver_fee_usd   = 0
        booking.total_usd        = 0
        booking.total_kes        = 0
        booking.total_eur        = 0
        booking.terms_accepted   = bool(cd.get('terms_accepted'))

        if request.user.is_authenticated:
            booking.user = request.user

        booking.calculate_totals()

        # On a meaningful edit, restart the reminder clock — the customer should
        # get a fresh reminder showing the new price 1 hour from now (if still
        # unpaid by then). Without this, an edited-up booking would either
        # never reminder again, or reminder with a stale price.
        if is_meaningful_edit:
            booking.payment_reminder_sent = False

        booking.save()

        # auto_now_add=True ignores explicit assignment to created_at, so use
        # queryset update to forcibly reset the reminder clock when the price changed.
        if is_meaningful_edit:
            Booking.objects.filter(pk=booking.pk).update(created_at=timezone.now())

        # Email admin about new booking immediately. The CUSTOMER reminder
        # ("Complete Payment") is delayed: it fires from the
        # management command `send_payment_reminders` after 1 hour, ONLY if
        # the booking is still unpaid. If they pay within the hour, no email.
        # Fire admin email + customer "we got your booking" email in a
        # background thread so the HTTP response returns immediately —
        # SMTP can take 1-3 seconds and would block the user.
        try:
            from .emails import send_new_booking_admin_alert, send_booking_received
            _fire_email(send_new_booking_admin_alert, booking)
            _fire_email(send_booking_received, booking)
        except Exception as e:
            logger.exception('Booking-creation email threads failed')

        # Optional account creation
        account_created     = False
        account_email_taken = False
        if cd.get('create_account') and cd.get('password'):
            existing = User.objects.filter(email__iexact=cd['email']).first()
            if existing:
                # Email already registered — refuse to silently re-create.
                # If they're logged in as that user, attach the booking to them.
                # Otherwise, return an error so the frontend can ask them to log in.
                if request.user.is_authenticated and request.user == existing:
                    booking.user = existing
                    booking.save(update_fields=['user'])
                else:
                    account_email_taken = True
                    logger.info('Account creation skipped — email already exists: %s', cd['email'])
            else:
                try:
                    new_user = User.objects.create_user(
                        username   = cd['email'],
                        email      = cd['email'],
                        password   = cd['password'],
                        first_name = cd['first_name'],
                        last_name  = cd['last_name'],
                    )
                    booking.user = new_user
                    booking.save(update_fields=['user'])
                    # Explicit backend — required when multiple AUTHENTICATION_BACKENDS
                    # are configured. Without it, Django raises ValueError.
                    login(request, new_user, backend='core.auth_backends.EmailOrUsernameBackend')
                    account_created = True
                except Exception as exc:
                    logger.exception('Account creation failed')

        # If the email is already taken, abort BEFORE creating the booking record
        # would be ideal, but the booking is already saved. Reverse that and ask
        # the user to log in first.
        if account_email_taken:
            booking.delete()
            return JsonResponse({
                'ok': False,
                'errors': {
                    'email': ['An account with this email already exists. '
                              'Please sign in first or use a different email.'],
                },
                'account_email_taken': True,
            }, status=400)

        request.session['pending_booking_id'] = booking.id

        # ── Corporate Hire: invoice instead of immediate payment ────────
        # Corporate clients expect to receive an invoice they can process
        # through their finance department, not a one-click checkout.
        # We mark the booking as 'invoiced', generate an invoice number,
        # set the due date (pickup minus 1 day), email the invoice, and
        # signal the frontend to skip Step 2 (payment) and show the
        # "invoice sent" confirmation directly.
        is_corporate = (booking.hire_type == 'corporate')
        if is_corporate:
            from datetime import timedelta as _td
            booking.payment_status   = 'invoiced'
            booking.invoice_number   = _make_invoice_number()
            booking.invoice_issued_at = timezone.now()
            # Due 1 day before pickup so we have time to confirm the vehicle.
            booking.invoice_due_date = booking.pickup_date - _td(days=1)
            booking.save(update_fields=[
                'payment_status', 'invoice_number',
                'invoice_issued_at', 'invoice_due_date',
            ])
            # Email the invoice in a background thread (same as other emails)
            try:
                from .emails import send_invoice_email
                _fire_email(send_invoice_email, booking)
            except Exception:
                logger.exception('Invoice email thread failed')

        return JsonResponse({
            'ok':              True,
            'reference':       booking.reference,
            'booking_id':      booking.id,
            'days':            days,
            'vehicle':         vehicle.name,
            'total_usd':       str(booking.total_usd),
            'total_kes':       str(booking.total_kes),
            'total_eur':       str(booking.total_eur),
            'driver_fee':      str(booking.driver_fee_usd),
            'base_price':      str(booking.base_price_usd),
            'with_driver':     booking.with_driver,
            'baby_seat':       booking.baby_seat,
            'baby_seat_fee':   '10.00' if booking.baby_seat else '0.00',
            'account_created': account_created,
            # Corporate-specific fields — frontend uses these to switch to
            # the invoice confirmation flow instead of the payment step.
            'is_invoiced':     is_corporate,
            'invoice_number':  booking.invoice_number if is_corporate else '',
            'invoice_url':     (request.build_absolute_uri(
                                    f'/invoice/{booking.reference}/'
                                ) if is_corporate else ''),
            'invoice_pdf_url': (request.build_absolute_uri(
                                    f'/invoice/{booking.reference}/pdf/'
                                ) if is_corporate else ''),
            'invoice_due':     (booking.invoice_due_date.strftime('%Y-%m-%d')
                                if is_corporate and booking.invoice_due_date else ''),
        })

    except Exception as exc:
        logger.error('booking_submit error: %s\n%s', exc, traceback.format_exc())
        return _json_error('Server error: ' + str(exc), 500)


# ─────────────────────────────────────────────────────────────
#  BOOKING SUMMARY
# ─────────────────────────────────────────────────────────────
@require_GET
def booking_summary(request):
    """
    Returns booking JSON for the payment-step UI. Two ways to identify the booking:
      1. ?reference=DK-2025-XXXXXX (public — works for unpaid bookings from check-booking page)
      2. session pending_booking_id (default — set after booking_submit)
    If the public reference points to a PAID booking, returns {ok: False,
    already_paid: True} so the JS can redirect the customer to the
    check-booking page instead of trying to pay again.
    """
    reference = (request.GET.get('reference') or '').strip()
    b = None

    if reference:
        # Public resume: look up the booking regardless of payment status.
        try:
            b = Booking.objects.get(reference=reference)
        except Booking.DoesNotExist:
            return _json_error('Booking not found.', 404)
        # If already paid, tell the JS so it can redirect to check-booking
        # (clicking "Complete Payment" in an old email shouldn't double-charge).
        if b.payment_status == 'paid':
            return JsonResponse({
                'ok':            False,
                'already_paid':  True,
                'reference':     b.reference,
            })
        request.session['pending_booking_id'] = b.id
    else:
        booking_id = request.session.get('pending_booking_id')
        if not booking_id:
            return _json_error('No pending booking.', 404)
        try:
            b = Booking.objects.get(id=booking_id)
        except Booking.DoesNotExist:
            return _json_error('Booking not found.', 404)

    try:
        is_transfer = (b.hire_type == 'transfer')
        return JsonResponse({
            'ok':          True,
            'reference':   b.reference,
            'vehicle':     b.vehicle.name if b.vehicle else 'Airport Transfer',
            'days':        b.days,
            'total_usd':   str(b.total_usd),
            'total_kes':   str(b.total_kes),
            'total_eur':   str(b.total_eur),
            'base_price':  str(b.base_price_usd),
            'driver_fee':  str(b.driver_fee_usd),
            'with_driver': b.with_driver,
            'baby_seat':   b.baby_seat,
            'baby_seat_fee': '10.00' if b.baby_seat else '0.00',
            'is_transfer': is_transfer,
        })
    except Exception as exc:
        return _json_error(str(exc), 500)


# ─────────────────────────────────────────────────────────────
#  BOOKING RESUME  (for unpaid bookings from dashboard)
# ─────────────────────────────────────────────────────────────
@require_POST
def booking_resume(request):
    """Re-attach an unpaid booking to the current session so the user can
    continue from Step 2 (payment) via the home page modal."""
    if not request.user.is_authenticated:
        return _json_error('Please sign in to resume a booking.', 401)
    try:
        booking_id = request.POST.get('booking_id')
        if not booking_id:
            return _json_error('No booking specified.')
        try:
            booking = Booking.objects.get(
                id=booking_id,
                user=request.user,
            )
        except Booking.DoesNotExist:
            return _json_error('Booking not found or not owned by you.', 404)

        # Only allow resuming unpaid or pending bookings
        if booking.payment_status == 'paid' and booking.status == 'confirmed':
            return _json_error('This booking is already confirmed and paid.')

        # Re-attach to session so payment_process can pick it up
        request.session['pending_booking_id'] = booking.id
        return JsonResponse({
            'ok':        True,
            'reference': booking.reference,
            'total_usd': str(booking.total_usd),
        })
    except Exception as exc:
        logger.error('booking_resume error: %s', exc)
        return _json_error('Could not resume booking.', 500)


@require_POST
def booking_extend(request):
    """
    Extend an existing PAID rental by N extra days.

    We do this by creating a SIBLING booking record covering only the
    extension window (original_return_date → original_return_date + N).
    Reasons for sibling-not-mutation:
      - The original booking stays paid and immutable, which keeps
        accounting straightforward.
      - Extension fails or is abandoned mid-payment → no half-broken state.
      - Email + reminder logic treats extensions like any other unpaid
        booking; we don't need a new "partial payment" status.

    Extensions are NOT allowed for:
      - Airport transfers (single-trip product)
      - Safari packages (re-quoting per destination is complex → WhatsApp)
      - Unpaid or cancelled original bookings
      - Bookings whose return date is in the past (too late to extend)
    """
    from datetime import timedelta as _td
    from decimal import Decimal

    if not request.user.is_authenticated:
        return _json_error('Please sign in to extend a booking.', 401)

    ref = (request.POST.get('reference') or '').strip().upper()
    try:
        extra_days = int(request.POST.get('extra_days') or 0)
    except (TypeError, ValueError):
        return _json_error('Invalid number of days.', 400)

    if extra_days < 1 or extra_days > 60:
        return _json_error('Extension must be 1–60 extra days.', 400)
    if not ref:
        return _json_error('No booking reference provided.', 400)

    try:
        original = Booking.objects.get(reference=ref, user=request.user)
    except Booking.DoesNotExist:
        return _json_error('Booking not found or not owned by you.', 404)

    # Eligibility checks
    if original.payment_status != 'paid':
        return _json_error('Only paid bookings can be extended.', 400)
    if original.hire_type == 'transfer':
        return _json_error('Airport transfers cannot be extended — book a new one.', 400)
    if original.hire_type == 'safari':
        return _json_error('Safari extensions require a custom quote — please WhatsApp us.', 400)
    if not original.return_date:
        return _json_error('Original booking has no return date — contact support.', 400)
    # One-extension-only rule: if an extension child already exists, refuse.
    # The customer can still extend further by contacting support directly.
    if original.has_extension:
        return _json_error(
            'This booking has already been extended once. '
            'For further extensions please WhatsApp us at +254 727 745 907.',
            400
        )
    # Also block extending an EXTENSION (extensions of extensions).
    # If this booking is itself the child of a parent, it can't be re-extended.
    if original.parent_booking_id:
        return _json_error(
            'Extension bookings cannot be extended further. '
            'Please WhatsApp us at +254 727 745 907 for additional days.',
            400
        )

    from django.utils import timezone
    today = timezone.localdate()
    if original.return_date < today:
        return _json_error('This booking ended already. Book a new one.', 400)

    if not original.vehicle:
        return _json_error('Original booking has no vehicle — contact support.', 400)

    # ── Build the extension booking ──────────────────────────────
    # Period: starts where the original ends, runs for `extra_days`.
    new_pickup = original.return_date
    new_return = new_pickup + _td(days=extra_days)

    daily = Decimal(str(original.daily_rate_usd or 0))
    if daily <= 0:
        return _json_error('Could not determine daily rate. Contact support.', 500)

    extra_usd = (daily * Decimal(extra_days)).quantize(Decimal('0.01'))
    KES_PER_USD = Decimal('130')
    EUR_PER_USD = Decimal('0.93')
    extra_kes = (extra_usd * KES_PER_USD).quantize(Decimal('1'))
    extra_eur = (extra_usd * EUR_PER_USD).quantize(Decimal('0.01'))

    ext = Booking(
        user             = request.user,
        first_name       = original.first_name,
        last_name        = original.last_name,
        email            = original.email,
        phone            = original.phone,
        nationality      = original.nationality,
        vehicle          = original.vehicle,
        hire_type        = original.hire_type,
        with_driver      = original.with_driver,
        baby_seat        = False,                # extensions don't re-charge baby seat
        pickup_location  = original.pickup_location,
        pickup_date      = new_pickup,
        pickup_time      = original.return_time or original.pickup_time,
        return_date      = new_return,
        return_time      = original.return_time or original.pickup_time,
        days             = extra_days,
        base_price_usd   = extra_usd,
        driver_fee_usd   = Decimal('0.00'),      # already bundled into daily for safari; for rentals daily includes it via daily_rate_usd
        total_usd        = extra_usd,
        total_kes        = extra_kes,
        total_eur        = extra_eur,
        terms_accepted   = True,                  # inherited from original
        parent_booking   = original,              # mark as extension of original
        ip_address       = get_client_ip(request),
        user_agent       = request.META.get('HTTP_USER_AGENT', '')[:500],
    )
    ext.save()

    # Tag the extension via existing JSON field if there's one suitable.
    # For now we just attach to session for payment flow.
    request.session['pending_booking_id'] = ext.id
    request.session['extension_of_ref']   = original.reference

    logger.info('Extension created: original=%s extension=%s extra_days=%d cost=$%s',
                original.reference, ext.reference, extra_days, extra_usd)

    return JsonResponse({
        'ok':                   True,
        'extension_reference':  ext.reference,
        'original_reference':   original.reference,
        'extra_days':           extra_days,
        'extra_usd':            float(extra_usd),
        'new_return_date':      new_return.strftime('%Y-%m-%d'),
    })


# ─────────────────────────────────────────────────────────────
#  INVOICE (corporate hire)
# ─────────────────────────────────────────────────────────────
@require_GET
def invoice_view(request, reference):
    """
    Public invoice page. Shown after a corporate-hire booking is submitted.
    The email sent to the customer links here. Anyone with the booking
    reference can view it — references are 6-char random hex, so this is
    a capability URL (similar to a Dropbox link). For higher security we
    could require email match, but for usability we just gate by reference.
    """
    try:
        booking = Booking.objects.get(reference=reference, hire_type='corporate')
    except Booking.DoesNotExist:
        return render(request, 'core/invoice_not_found.html', status=404)

    return render(request, 'core/invoice.html', {
        'booking': booking,
        # Pre-rendered absolute URLs for buttons
        'pdf_url': request.build_absolute_uri(
            f'/invoice/{booking.reference}/pdf/'),
        'pay_url': request.build_absolute_uri(
            f'/?resume={booking.reference}'),
    })


@require_GET
def invoice_pdf(request, reference):
    """
    Returns the invoice as a PDF download.
    Uses ReportLab — already in requirements.txt for the rest of the app.
    Falls back to HTML download if PDF generation fails for any reason.
    """
    try:
        booking = Booking.objects.get(reference=reference, hire_type='corporate')
    except Booking.DoesNotExist:
        return HttpResponse('Invoice not found', status=404)

    try:
        from .pdf_invoice import render_invoice_pdf
        pdf_bytes = render_invoice_pdf(booking)
    except Exception as exc:
        logger.exception('PDF render failed for invoice %s: %s', reference, exc)
        # Fall back to HTML — better than a 500.
        return render(request, 'core/invoice.html', {
            'booking': booking,
            'pdf_url': '',
            'pay_url': request.build_absolute_uri(f'/?resume={booking.reference}'),
        })

    fname = f'invoice-{booking.invoice_number or booking.reference}.pdf'
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


# ─────────────────────────────────────────────────────────────
#  PAYMENT PROCESS  (Step 2)
# ─────────────────────────────────────────────────────────────
@require_POST
def payment_attempt(request):
    """
    Lightweight endpoint hit by the frontend the moment a customer clicks any
    payment button (Paystack popup, PayPal Smart Button, or M-Pesa "Send STK").
    Stamps `payment_attempt_at` so the reminder cron skips this booking — the
    customer is actively in checkout, no need to nag them.
    """
    try:
        booking_id = request.session.get('pending_booking_id')
        if not booking_id:
            return JsonResponse({'ok': False, 'error': 'session_expired'}, status=400)

        try:
            booking = Booking.objects.get(pk=booking_id, payment_status='unpaid')
        except Booking.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'booking_not_found'}, status=404)

        # Use queryset .update() so we don't trip auto_now on updated_at, and
        # so we don't accidentally clobber other fields if signals fire.
        Booking.objects.filter(pk=booking.pk).update(payment_attempt_at=timezone.now())
        return JsonResponse({'ok': True})
    except Exception as exc:
        logger.error('payment_attempt error: %s', exc)
        return JsonResponse({'ok': False, 'error': 'server_error'}, status=500)


@require_POST
def payment_process(request):
    try:
        booking_id = request.session.get('pending_booking_id')
        if not booking_id:
            return _json_error('Session expired. Please start your booking again.')

        try:
            booking = Booking.objects.get(id=booking_id, status='pending')
        except Booking.DoesNotExist:
            return _json_error('Booking not found or already processed.', 404)

        form = BookingPaymentForm(request.POST)
        if not form.is_valid():
            errors = {k: v[0] if isinstance(v, list) else str(v)
                      for k, v in form.errors.items()}
            return JsonResponse({'ok': False, 'errors': errors}, status=400)

        cd     = form.cleaned_data
        method = cd['payment_method']
        result = {}

        if method == 'paystack':
            # Paystack popup posts back a `reference` after the user pays
            result = PaystackBackend.verify(
                booking, cd.get('paystack_ref', ''))

        elif method == 'paypal':
            result = PayPalBackend.capture_order(
                booking, cd.get('paypal_order_id', ''))

        elif method == 'mpesa':
            result = MpesaBackend.stk_push(booking, cd.get('mpesa_phone', ''))
            if result['success']:
                booking.payment_method = 'mpesa'
                booking.payment_ref    = result['ref']
                booking.save(update_fields=['payment_method', 'payment_ref'])
                PaymentLog.objects.create(
                    booking      = booking,
                    method       = 'mpesa',
                    gateway_ref  = result['ref'],
                    amount_usd   = booking.total_usd,
                    status       = 'stk_pending',
                    raw_response = json.dumps(result.get('raw', {})),
                )
                return JsonResponse({
                    'ok':        True,
                    'async':     True,
                    'reference': booking.reference,
                    'message':   result['message'],
                })
            else:
                return _json_error(result.get('message', 'M-Pesa push failed.'))

        # Synchronous result (Paystack / PayPal)
        PaymentLog.objects.create(
            booking      = booking,
            method       = method,
            gateway_ref  = result.get('ref', ''),
            amount_usd   = booking.total_usd,
            status       = 'success' if result.get('success') else 'failed',
            raw_response = json.dumps(result.get('raw', {})),
        )

        if result.get('success'):
            booking.payment_method = method
            booking.payment_ref    = result.get('ref', '')
            booking.payment_status = 'paid'
            booking.status         = 'confirmed'
            booking.payment_reminder_sent = True   # never email a paid booking
            booking.save(update_fields=[
                'payment_method', 'payment_ref', 'payment_status', 'status',
                'payment_reminder_sent'])
            # Three emails: customer confirmation, customer receipt, admin alert.
            # Fire all in background threads — payment success page returns instantly.
            try:
                from .emails import send_payment_receipt, send_payment_admin_alert
                for fn in (send_booking_confirmation, send_payment_receipt, send_payment_admin_alert):
                    _fire_email(fn, booking)
            except Exception as e:
                logger.exception('Post-payment email threads failed')
            request.session.pop('pending_booking_id', None)
            return JsonResponse({
                'ok':        True,
                'reference': booking.reference,
                'message':   'Payment successful! Your booking is confirmed.',
            })
        else:
            return _json_error(result.get('message', 'Payment failed. Please try again.'))

    except Exception as exc:
        logger.error('payment_process error: %s\n%s', exc, traceback.format_exc())
        return _json_error('Server error during payment. Please try again.', 500)


# ─────────────────────────────────────────────────────────────
#  M-PESA CALLBACK
# ─────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def mpesa_callback(request):
    try:
        payload = json.loads(request.body)
        result  = MpesaBackend.handle_callback(payload)
        if result['success']:
            try:
                booking = Booking.objects.get(
                    payment_ref=result.get('checkout_id', ''))
                booking.payment_status = 'paid'
                booking.status         = 'confirmed'
                booking.save(update_fields=['payment_status', 'status'])
                PaymentLog.objects.filter(
                    booking=booking, method='mpesa').update(
                    status='success', gateway_ref=result.get('mpesa_code', ''))
                send_booking_confirmation(booking)
            except Booking.DoesNotExist:
                logger.warning('M-Pesa callback: booking not found for %s',
                               result.get('checkout_id'))
        else:
            logger.info('M-Pesa callback failed: %s', result.get('message'))
    except Exception as exc:
        logger.error('M-Pesa callback error: %s', exc)
    return HttpResponse('OK')


# ─────────────────────────────────────────────────────────────
#  PAYSTACK WEBHOOK
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
#  PAYSTACK WEBHOOK
# ─────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def paystack_webhook(request):
    """
    Paystack webhook receiver.
    Verifies HMAC-SHA512 signature against our secret key, then processes
    the `charge.success` event to confirm the booking.

    Set the webhook URL in Paystack dashboard:
      https://dashboard.paystack.com/#/settings/developers  → Webhook URL
      → https://yourdomain.com/payments/paystack/webhook/
    """
    import hashlib
    import hmac

    try:
        secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        incoming   = request.headers.get('x-paystack-signature', '')

        # Verify signature: HMAC-SHA512(body, secret_key)
        if secret_key:
            computed = hmac.new(
                secret_key.encode('utf-8'),
                request.body,
                hashlib.sha512,
            ).hexdigest()
            if not hmac.compare_digest(computed, incoming):
                logger.warning('Paystack webhook signature mismatch')
                return HttpResponse(status=401)

        payload = json.loads(request.body)

        if payload.get('event') == 'charge.success':
            data      = payload.get('data', {}) or {}
            reference = data.get('reference', '')
            if reference:
                # Paystack sends back the SUFFIXED ref we passed at popup time
                # (e.g. DK-2026-XXXXXX-abc123). Look up by:
                #   1. payment_ref (exact match for the suffixed ref we stored)
                #   2. reference   (exact match if no suffix was used)
                #   3. reference   (prefix match — strip our suffix)
                # That way ALL three call paths line up: JS callback, webhook,
                # and any old bookings that pre-date the suffixing change.
                booking = (
                    Booking.objects.filter(payment_ref=reference).first()
                    or Booking.objects.filter(reference=reference).first()
                )
                if booking is None and '-' in reference:
                    # Suffix scheme is "{booking.reference}-{6-char-suffix}".
                    # If the trailing segment is short, treat the rest as the booking ref.
                    parts = reference.rsplit('-', 1)
                    if len(parts) == 2 and 4 <= len(parts[1]) <= 10:
                        booking = Booking.objects.filter(reference=parts[0]).first()

                if booking and booking.payment_status != 'paid':
                    booking.payment_status = 'paid'
                    booking.status         = 'confirmed'
                    booking.payment_method = booking.payment_method or 'paystack'
                    booking.payment_ref    = data.get('reference', booking.payment_ref)
                    booking.payment_reminder_sent = True
                    booking.save(update_fields=[
                        'payment_status', 'status', 'payment_method', 'payment_ref',
                        'payment_reminder_sent'])
                    # Fire customer + admin emails in background threads
                    try:
                        from .emails import (send_booking_confirmation,
                                              send_payment_receipt,
                                              send_payment_admin_alert)
                        for fn in (send_booking_confirmation, send_payment_receipt, send_payment_admin_alert):
                            _fire_email(fn, booking)
                    except Exception as e:
                        logger.exception('Webhook email threads failed for %s', reference)
                    logger.info('Paystack webhook confirmed booking: %s (payment_ref=%s)',
                                booking.reference, reference)
                elif booking:
                    logger.info('Paystack webhook for already-paid booking: %s', booking.reference)
                else:
                    logger.warning('Paystack webhook: no booking found for reference %s', reference)

    except Exception as exc:
        logger.error('Paystack webhook error: %s', exc)
        return HttpResponse(status=400)

    return HttpResponse(status=200)


# ─────────────────────────────────────────────────────────────
#  PAYPAL CREATE ORDER
# ─────────────────────────────────────────────────────────────
@require_POST
def paypal_create_order(request):
    try:
        booking_id = request.session.get('pending_booking_id')
        if not booking_id:
            return _json_error('No pending booking.')
        booking = Booking.objects.get(id=booking_id, status='pending')
        result  = PayPalBackend.create_order(booking)
        if result.get('success'):
            return JsonResponse({'ok': True, 'orderID': result['order_id']})
        return _json_error(result.get('message', 'PayPal error.'))
    except Booking.DoesNotExist:
        return _json_error('Booking not found.', 404)
    except Exception as exc:
        logger.error('paypal_create_order error: %s', exc)
        return _json_error(str(exc), 500)


# ─────────────────────────────────────────────────────────────
#  CHECK BOOKING
# ─────────────────────────────────────────────────────────────
def check_booking(request):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        ref = request.GET.get('reference', '').strip().upper()
        if not ref:
            return _json_error('No reference provided.')
        try:
            b = Booking.objects.get(reference=ref)
            is_transfer = (b.hire_type == 'transfer')

            # For airport transfers, the customer chose a CAR CLASS (Economy /
            # Mid-size / Luxury / Van) — not a specific vehicle — so we hide
            # the assigned vehicle name and show "Airport Transfer · {class}"
            # as the service label instead.
            if is_transfer:
                class_label = b.get_transfer_car_type_display() or ''
                service_label = (
                    f'Airport Transfer · {class_label}'.rstrip(' ·')
                )
            else:
                service_label = b.vehicle.name if b.vehicle else '—'

            return JsonResponse({
                'ok':          True,
                'reference':   b.reference,
                'hire_type':   b.get_hire_type_display(),
                'is_transfer': is_transfer,
                # For transfers: "Airport Transfer · Mid-size"
                # For rentals:   actual vehicle name
                'vehicle':     service_label,
                'pickup':      b.get_pickup_location_display(),
                'pickup_date': b.pickup_date.strftime('%d %b %Y'),
                # Airport transfers are one-way — no return date.
                'return_date': b.return_date.strftime('%d %b %Y') if b.return_date else '— (one-way)',
                'status':      b.get_status_display(),
                'payment':     b.get_payment_status_display(),
                'total_usd':   str(b.total_usd),
                'total_kes':   str(b.total_kes),
                'with_driver': b.with_driver,
                'transfer_zone':        b.get_transfer_zone_display() if is_transfer else '',
                'transfer_car_type':    b.get_transfer_car_type_display() if is_transfer else '',
                'transfer_destination': b.transfer_destination if is_transfer else '',
            })
        except Booking.DoesNotExist:
            return _json_error('No booking found for that reference.', 404)
        except Exception as exc:
            return _json_error(str(exc), 500)

    form   = CheckBookingForm(request.GET or None)
    result = None
    if form.is_valid():
        try:
            result = Booking.objects.get(reference=form.cleaned_data['reference'])
        except Booking.DoesNotExist:
            messages.error(request, 'No booking found for that reference.')
    return render(request, 'core/check_booking.html', {'form': form, 'booking': result})


# ─────────────────────────────────────────────────────────────
#  AUTH — fixed next redirect (was passing URL string not name)
# ─────────────────────────────────────────────────────────────
def auth_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    # ── Brute-force lockout: 5 failed attempts per IP per 15 minutes ──
    from django.core.cache import cache
    from .middleware import get_client_ip
    ip = get_client_ip(request) or 'unknown'
    lockout_key = f'login_fails:{ip}'
    fails = cache.get(lockout_key, 0)
    if fails >= 5:
        return render(request, 'core/auth/login.html', {
            'form': LoginForm(),
            'lockout_error': (
                'Too many failed login attempts. Please wait 15 minutes and try again, '
                'or reset your password.'
            ),
        })

    form = LoginForm(data=request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            # Successful login → clear failure counter
            cache.delete(lockout_key)
            login(request, user)
            next_url = request.GET.get('next', '').strip()
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('dashboard')
        else:
            # Failed attempt → increment counter (15-minute TTL)
            cache.set(lockout_key, fails + 1, timeout=900)

    return render(request, 'core/auth/login.html', {'form': form})


def auth_logout(request):
    logout(request)
    return redirect('home')


@never_cache
def auth_register(request):
    """
    Step 1 of new-account creation:
    - Validates the form
    - Creates the user with is_active=False (cannot log in until verified)
    - Generates a 6-digit OTP, emails it
    - Redirects to /auth/verify-email/ where the user enters the code

    If a user with this email exists but is INACTIVE (started signup but
    never verified the OTP), we delete that stale record so the new
    registration succeeds. Handles "I made a typo and want to retry".
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    # Clear any stale OTP session state from a previous incomplete attempt
    request.session.pop('otp_user_pk', None)

    # Pre-flight: delete inactive (unverified) records that match the email
    # or username being registered. Stops UserCreationForm uniqueness checks
    # from blocking the retry.
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().lower()
        if email:
            stale = User.objects.filter(email__iexact=email, is_active=False).first()
            if stale:
                logger.info('Deleting stale inactive registration for %s', email)
                EmailOTP.objects.filter(email__iexact=email).delete()
                stale.delete()

        username = (request.POST.get('username') or '').strip()
        if username:
            stale = User.objects.filter(username__iexact=username, is_active=False).first()
            if stale:
                logger.info('Deleting stale inactive username %s', username)
                EmailOTP.objects.filter(email__iexact=stale.email).delete()
                stale.delete()

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        user.is_active = False  # cannot log in until OTP verified
        user.save()
        if hasattr(form, 'save_m2m'):
            try:
                form.save_m2m()
            except Exception:
                pass
        _create_and_send_otp(user)
        request.session['otp_user_pk'] = user.pk
        messages.info(request, f'We just emailed a 6-digit code to {user.email}. Enter it below to finish creating your account.')
        return redirect('verify_email')
    return render(request, 'core/auth/register.html', {'form': form})


@never_cache
def verify_email(request):
    """
    Step 2 of new-account creation: user enters the OTP they received.
    On success: activates the user, logs them in, redirects to dashboard.
    On failure: logs an attempt; after 5 wrong codes the OTP is invalidated.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    user_pk = request.session.get('otp_user_pk')
    if not user_pk:
        messages.error(request, 'No verification in progress. Please register again.')
        return redirect('register')

    try:
        user = User.objects.get(pk=user_pk, is_active=False)
    except Exception:
        messages.error(request, 'Verification expired. Please register again.')
        return redirect('register')

    otp = EmailOTP.objects.filter(
        email__iexact=user.email, verified_at__isnull=True,
    ).order_by('-created_at').first()

    if request.method == 'POST':
        action = request.POST.get('action', 'verify')
        if action == 'resend':
            if otp and otp.created_at and (timezone.now() - otp.created_at).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS:
                wait = OTP_RESEND_COOLDOWN_SECONDS - int((timezone.now() - otp.created_at).total_seconds())
                messages.warning(request, f'Please wait {wait}s before requesting a new code.')
            else:
                _create_and_send_otp(user)
                messages.success(request, 'A new code has been sent to your email.')
            return redirect('verify_email')

        # Default: verify the entered code
        entered = (request.POST.get('code') or '').strip()
        if not otp:
            messages.error(request, 'No active code. Click "Resend code".')
        elif otp.is_expired():
            messages.error(request, 'This code has expired. Click "Resend code" to get a fresh one.')
        elif otp.attempts >= OTP_MAX_ATTEMPTS:
            messages.error(request, 'Too many wrong attempts. Click "Resend code" to get a fresh one.')
        elif entered == otp.code:
            otp.verified_at = timezone.now()
            otp.save(update_fields=['verified_at'])
            user.is_active = True
            user.save(update_fields=['is_active'])
            login(request, user, backend='core.auth_backends.EmailOrUsernameBackend')
            request.session.pop('otp_user_pk', None)
            messages.success(request, f'Welcome aboard, {user.first_name}! Your email is verified.')
            return redirect('dashboard')
        else:
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            remaining = max(0, OTP_MAX_ATTEMPTS - otp.attempts)
            messages.error(request, f'Incorrect code. {remaining} attempt(s) left before this code is invalidated.')

    return render(request, 'core/auth/verify_email.html', {
        'email': user.email,
        'expires_minutes': OTP_EXPIRY_MINUTES,
    })


# ─────────────────────────────────────────────────────────────
#  MY ACCOUNT HUB (dashboard + password + delete)
# ─────────────────────────────────────────────────────────────
from django.contrib.auth import update_session_auth_hash


@login_required
def dashboard(request):
    """My Account hub with bookings and account settings."""
    today = timezone.now().date()

    # ── Claim orphan bookings carefully ──
    # ONLY claim bookings that:
    #   (a) have user=None (orphan)
    #   (b) match this user's email exactly
    #   (c) were created BEFORE this user account existed (1-hr buffer)
    #   (d) this user has no bookings yet (first-login claim only)
    # Conditions (c)+(d) prevent another guest's later booking from accidentally
    # landing in someone else's account if they share an email.
    try:
        already_has = Booking.objects.filter(user=request.user).exists()
        if not already_has:
            orphans = Booking.objects.filter(
                user__isnull=True,
                email__iexact=request.user.email,
                created_at__lte=request.user.date_joined + timezone.timedelta(hours=1),
            )
            if orphans.exists():
                count = orphans.update(user=request.user)
                if count:
                    logger.info('Claimed %d orphan bookings for user %s', count, request.user.email)
    except Exception as exc:
        logger.exception('Orphan claim skipped')

    try:
        # Show ONLY bookings where BOTH user FK matches AND email matches.
        # The double check prevents cross-account leak in case anything ever
        # mis-attaches (e.g. mistaken admin bulk-update).
        all_bookings = list(Booking.objects.filter(
            user=request.user,
            email__iexact=request.user.email,
        ).order_by('-created_at'))
    except Exception:
        all_bookings = []

    # Bookings without return_date (airport transfers) are "active" if they
    # have a future PICKUP date and aren't completed/cancelled. Past = pickup
    # date already passed OR explicitly completed/cancelled.
    def _is_active(b):
        if b.status in ('completed', 'cancelled'):
            return False
        ref_date = b.return_date or b.pickup_date  # transfers use pickup
        return ref_date is None or ref_date >= today

    def _is_past(b):
        if b.status in ('completed', 'cancelled'):
            return True
        ref_date = b.return_date or b.pickup_date
        return ref_date is not None and ref_date < today

    active_bookings = [b for b in all_bookings if _is_active(b)]
    past_bookings   = [b for b in all_bookings if _is_past(b)]

    # Calculate total spent
    total_spent = sum(float(b.total_usd or 0) for b in all_bookings)

    return render(request, 'core/dashboard.html', {
        'user':            request.user,
        'bookings':        all_bookings,
        'active_bookings': active_bookings,
        'past_bookings':   past_bookings,
        'active_count':    len(active_bookings),
        'total_spent':     f"{total_spent:.2f}",
        'active_tab':      request.GET.get('tab', 'active'),
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    })


# ─────────────────────────────────────────────────────────────
#  ACCOUNT — change password (AJAX, toast-driven)
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def change_password(request):
    """
    AJAX password change. Returns JSON with a clear, user-facing message.
    Frontend toasts on the result.
    """
    old_pw  = request.POST.get('old_password', '')
    new_pw1 = request.POST.get('new_password1', '')
    new_pw2 = request.POST.get('new_password2', '')

    # 1. Current password must be correct
    if not request.user.check_password(old_pw):
        return JsonResponse({
            'ok': False, 'field': 'old_password',
            'error': 'Current password is incorrect.',
        }, status=400)

    # 2. Both new password fields required
    if not new_pw1 or not new_pw2:
        return JsonResponse({
            'ok': False, 'field': 'new_password1',
            'error': 'Please enter your new password in both fields.',
        }, status=400)

    # 3. Length check first (most common failure)
    if len(new_pw1) < 8:
        return JsonResponse({
            'ok': False, 'field': 'new_password1',
            'error': 'New password must be at least 8 characters long.',
        }, status=400)

    # 4. Must match
    if new_pw1 != new_pw2:
        return JsonResponse({
            'ok': False, 'field': 'new_password2',
            'error': 'New passwords do not match.',
        }, status=400)

    # 5. Don't allow same as old
    if new_pw1 == old_pw:
        return JsonResponse({
            'ok': False, 'field': 'new_password1',
            'error': 'New password must be different from your current password.',
        }, status=400)

    # 6. Run Django's password validators (common-password, numeric-only, etc.)
    try:
        from django.contrib.auth.password_validation import validate_password
        validate_password(new_pw1, request.user)
    except ValidationError as e:
        return JsonResponse({
            'ok': False, 'field': 'new_password1',
            'error': '; '.join(e.messages),
        }, status=400)

    # 7. Save & keep user logged in
    request.user.set_password(new_pw1)
    request.user.save()
    update_session_auth_hash(request, request.user)
    return JsonResponse({
        'ok': True,
        'message': 'Password updated successfully.',
    })


@login_required
@require_POST
def delete_account(request):
    """
    AJAX account deletion. Requires the user's current password to confirm.
    On success deletes the user and logs out. Frontend redirects home.
    """
    password = request.POST.get('password', '')

    if not password:
        return JsonResponse({
            'ok': False,
            'error': 'Please enter your password to confirm deletion.',
        }, status=400)

    if not request.user.check_password(password):
        return JsonResponse({
            'ok': False,
            'error': 'Incorrect password. Account not deleted.',
        }, status=400)

    # All good — delete
    user = request.user
    logout(request)
    user.delete()
    return JsonResponse({
        'ok': True,
        'message': 'Your account has been permanently deleted.',
        'redirect': '/',
    })


# ─────────────────────────────────────────────────────────────
#  SUPPORT
# ─────────────────────────────────────────────────────────────
def support(request):
    form      = SupportForm(request.POST or None)
    submitted = False
    if request.method == 'POST':
        if form.is_valid():
            try:
                ticket            = form.save(commit=False)
                ticket.ip_address = get_client_ip(request)
                ticket.save()
                try:
                    send_support_notification(ticket)
                except Exception:
                    logger.exception('Support email failed')
                submitted = True
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'ok': True, 'ticket_id': ticket.id})
                messages.success(
                    request, "Your message has been sent. We'll reply within 24 hours.")
                return redirect('support')
            except Exception as exc:
                logger.error('support submit error: %s', exc)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return _json_error(str(exc), 500)
        elif request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            errors = {k: v[0] if isinstance(v, list) else str(v)
                      for k, v in form.errors.items()}
            return JsonResponse({'ok': False, 'errors': errors}, status=400)

    return render(request, 'core/support.html', {
        'form': form, 'submitted': submitted})


# ─────────────────────────────────────────────────────────────
#  FLEET PAGE
# ─────────────────────────────────────────────────────────────
def fleet(request):
    vehicles = Vehicle.objects.filter(is_available=True)
    return render(request, 'core/fleet.html', {'vehicles': vehicles})


# ═════════════════════════════════════════════════════════════
#  SEO PAGES — Vehicle details, Locations, About, Robots
# ═════════════════════════════════════════════════════════════
def vehicle_detail(request, slug):
    """
    SEO-optimized detail page for each vehicle. Generates a unique page per
    vehicle — each one ranks independently for long-tail queries like
    "Toyota Prado for hire in Nairobi" or "Land Cruiser rental Kenya".
    """
    vehicle = get_object_or_404(Vehicle, slug=slug, is_available=True)
    # Related vehicles (same category or badge)
    related = Vehicle.objects.filter(
        is_available=True,
    ).exclude(id=vehicle.id)[:4]
    return render(request, 'core/vehicle_detail.html', {
        'vehicle':          vehicle,
        'related':          related,
        'whatsapp_number':  getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
        'paystack_pk':      getattr(settings, 'PAYSTACK_PUBLIC_KEY', ''),
        'paypal_client_id': getattr(settings, 'PAYPAL_CLIENT_ID', ''),
    })


def _location_context(location_key):
    """Per-location content — drives a single shared template."""
    LOCATIONS = {
        'nairobi': {
            'key': 'nairobi',
            'h1': 'Car Rental in Nairobi, Kenya',
            'tagline': 'Self-drive and chauffeur services across Nairobi — from the CBD to Westlands, Karen and Kilimani.',
            'title': 'Car Rental in Nairobi Kenya | Self Drive & Chauffeur from $28/day | Munwan Car Rental',
            'meta_description': 'Affordable car rental in Nairobi, Kenya from $28/day. Self-drive or with driver. Free delivery to CBD, Westlands, Karen, Kilimani and JKIA airport. Pay by M-Pesa or card.',
            'url_name': 'location_nairobi',
            'hero_icon': '🏙️',
            'intro_p1': 'Nairobi is the capital of Kenya and the gateway to East Africa\'s best safari experiences. Whether you\'re a business traveller attending a conference in the CBD, a tourist arriving at Jomo Kenyatta International Airport, or a Nairobi resident heading upcountry, <strong>Munwan Car Rental</strong> offers affordable car rental in Nairobi with free delivery across the city.',
            'intro_p2': 'Our fleet ranges from economy saloons ideal for navigating Nairobi traffic (Mazda Demio, Toyota Fielder) to rugged 4x4s for safari trips (Toyota Prado, Land Cruiser). All rentals include <strong>full insurance, GPS tracking and 24/7 support</strong>.',
            'delivery_spots': [
                ('🏙️', 'Nairobi CBD', 'Free delivery to any office or hotel in the CBD — Kenyatta Avenue, Moi Avenue, Standard Street.'),
                ('🌳', 'Westlands', 'Village Market, Sarit Centre, The Mall Westlands — we deliver to your location.'),
                ('🏡', 'Karen &amp; Langata', 'Karen Country Club, Giraffe Centre area, and residential estates in Karen.'),
                ('🍽️', 'Kilimani &amp; Yaya', 'Yaya Centre, Prestige Plaza, Kilimani apartments and guesthouses.'),
                ('✈️', 'JKIA Airport', 'Meet-and-greet at Terminals 1 &amp; 2 with a Munwan Car Rental name board.'),
                ('✈️', 'Wilson Airport', 'Ideal for safari charter flights to the Mara or Amboseli.'),
            ],
            'popular_trips': [
                ('Nairobi → Maasai Mara', '~5–6 hours · 4x4 recommended', '280 km via Narok'),
                ('Nairobi → Amboseli', '~4 hours · 4x4 required for park roads', '230 km via Namanga Road'),
                ('Nairobi → Naivasha', '~1.5 hours · any vehicle', '90 km on A104 highway'),
                ('Nairobi → Mombasa', '~8 hours · saloon or SUV', '485 km on A109'),
            ],
            'best_cars': ['Mazda Demio', 'Toyota Fielder', 'Toyota Rav4', 'Nissan X-Trail'],
        },
        'jkia': {
            'key': 'jkia',
            'h1': 'Car Hire at Jomo Kenyatta International Airport (JKIA)',
            'tagline': 'Free meet-and-greet at JKIA — your car waits the moment you land.',
            'title': 'Car Rental at JKIA Airport Nairobi | Free Meet-and-Greet | Munwan Car Rental',
            'meta_description': 'Car rental at Jomo Kenyatta International Airport (JKIA) Nairobi. Free meet-and-greet at Terminals 1 & 2. Book safari 4x4s and saloons from $28/day. Pay by card, M-Pesa or PayPal.',
            'url_name': 'location_jkia',
            'hero_icon': '✈️',
            'intro_p1': 'Booking a car for pickup at <strong>Jomo Kenyatta International Airport (JKIA)</strong>? Munwan Car Rental offers <strong>free meet-and-greet at both Terminal 1 (international) and Terminal 2 (domestic)</strong>, 24 hours a day. A Munwan Car Rental representative waits at the arrivals exit holding a name board the moment you clear customs.',
            'intro_p2': 'There\'s no airport surcharge — pickup at JKIA is <strong>included in the rental rate</strong>. We\'ll help with luggage, show you the vehicle controls, and hand over keys with a full tank. Payment via Paystack (cards) or M-Pesa is completed before you land, so everything is ready.',
            'delivery_spots': [
                ('🛬', 'Terminal 1 (International)', 'Meet-and-greet at the international arrivals exit, 24/7.'),
                ('🛫', 'Terminal 2 (Domestic)', 'For connecting domestic flights from Kisumu, Mombasa, Eldoret.'),
                ('🚐', 'Shuttle Service', 'If you prefer, we\'ll meet you at your hotel after a free shuttle transfer.'),
                ('📱', 'WhatsApp Updates', 'Flight delayed? No problem — we track your flight in real time.'),
            ],
            'popular_trips': [
                ('JKIA → Nairobi CBD', '~45 mins in traffic · saloon OK', '18 km via Mombasa Road'),
                ('JKIA → Maasai Mara', '~6 hours · 4x4 required', '280 km via Nairobi &amp; Narok'),
                ('JKIA → Amboseli', '~4.5 hours · 4x4 recommended', '220 km via Namanga Road'),
                ('JKIA → Mombasa', '~8 hours · saloon or SUV', '485 km via A109'),
            ],
            'best_cars': ['Toyota Prado (safari)', 'Toyota Alphard (families)', 'Toyota Harrier (executive)', 'Toyota Fielder (budget)'],
        },
        'mombasa': {
            'key': 'mombasa',
            'h1': 'Car Rental in Mombasa, Kenya',
            'tagline': 'Coastal car hire — from Mombasa Airport to Diani Beach and Nyali.',
            'title': 'Car Rental in Mombasa Kenya | Airport Pickup | Diani Beach | Munwan Car Rental',
            'meta_description': 'Affordable car rental in Mombasa, Kenya. Free pickup at Moi International Airport. Drive to Diani Beach, Nyali, Watamu or Malindi. Self-drive or with driver. M-Pesa, card & PayPal accepted.',
            'url_name': 'location_mombasa',
            'hero_icon': '🏖️',
            'intro_p1': 'Planning a trip to Kenya\'s stunning coastal region? <strong>Munwan Car Rental offers car rental in Mombasa</strong> with free pickup at Moi International Airport. Whether you\'re heading to the white sands of <strong>Diani Beach</strong>, the coral reefs of <strong>Watamu</strong>, or the historic Old Town of Mombasa itself, we have the right vehicle.',
            'intro_p2': 'The coastal climate means you want reliable air conditioning and comfortable seating for longer journeys. Our fleet includes fuel-efficient saloons and family-friendly SUVs, all with cold AC, GPS, and 24/7 roadside support across the coast.',
            'delivery_spots': [
                ('✈️', 'Moi International Airport', 'Free meet-and-greet at arrivals, 24 hours.'),
                ('🏖️', 'Nyali &amp; Bamburi', 'Hotel delivery to Voyager, Serena, Bamburi Beach Hotel.'),
                ('🌴', 'Diani Beach', 'Direct delivery to Diani hotels and Airbnb properties.'),
                ('🏛️', 'Mombasa Old Town', 'Delivery to CBD and the historic Fort Jesus area.'),
            ],
            'popular_trips': [
                ('Mombasa → Diani Beach', '~1 hour + Likoni Ferry', '30 km via Likoni crossing'),
                ('Mombasa → Watamu', '~2 hours · any vehicle', '110 km via Malindi Road'),
                ('Mombasa → Tsavo East', '~3 hours · 4x4 recommended', '220 km via A109'),
                ('Mombasa → Nairobi', '~8 hours · saloon or SUV', '485 km via A109'),
            ],
            'best_cars': ['Toyota Noah (family)', 'Toyota Rav4 (beach trips)', 'Mazda Demio (economy)', 'Toyota Harrier (comfort)'],
        },
        'diani': {
            'key': 'diani',
            'h1': 'Car Rental in Diani Beach, Kenya',
            'tagline': 'Explore Kenya\'s most beautiful coastline on your own schedule.',
            'title': 'Car Rental Diani Beach Kenya | Self Drive Car Hire | Munwan Car Rental',
            'meta_description': 'Car rental in Diani Beach, Kenya. Perfect for exploring the South Coast — Galu Beach, Tiwi, Shimba Hills National Reserve. Free hotel delivery. Pay by M-Pesa, card or PayPal.',
            'url_name': 'location_diani',
            'hero_icon': '🌴',
            'intro_p1': 'Diani Beach is Kenya\'s premier coastal holiday destination — 25 km of powder-white sand, turquoise ocean, and world-class hotels. <strong>Munwan Car Rental offers car rental in Diani Beach</strong> with free delivery to any hotel, villa, or Airbnb along the coast.',
            'intro_p2': 'A rental car gives you the freedom to explore beyond the beach: venture into <strong>Shimba Hills National Reserve</strong> to see elephants, visit <strong>Wasini Island</strong> for dolphin-watching, or drive down to <strong>Tiwi Beach</strong> for a quieter swim. All our Diani rentals include full insurance and 24/7 coastal support.',
            'delivery_spots': [
                ('🏨', 'Diani Hotels', 'Swahili Beach, Leopard Beach, Baobab Beach — free delivery to any hotel.'),
                ('🏡', 'Villas &amp; Airbnb', 'Direct delivery to private villas and short-term rentals.'),
                ('✈️', 'Ukunda Airstrip', 'Pickup if you\'re flying in via light aircraft from Nairobi.'),
                ('🏖️', 'Galu Beach', 'Southern Diani delivery available.'),
            ],
            'popular_trips': [
                ('Diani → Mombasa', '~1 hour + Likoni Ferry', '30 km via Likoni crossing'),
                ('Diani → Shimba Hills', '~45 mins · 4x4 recommended', '35 km inland'),
                ('Diani → Wasini Island', '~1.5 hours + boat', '75 km south to Shimoni'),
                ('Diani → Tsavo East', '~3.5 hours · 4x4 required', '250 km north via A109'),
            ],
            'best_cars': ['Toyota Rav4 (versatile)', 'Nissan X-Trail (rough roads)', 'Toyota Fielder (economy)', 'Toyota Prado (safari)'],
        },
    }
    data = LOCATIONS.get(location_key, LOCATIONS['nairobi'])
    try:
        vehicles = list(Vehicle.objects.filter(is_available=True)[:6])
    except Exception:
        vehicles = []
    return {
        'loc':             data,
        'vehicles':        vehicles,
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    }


def loc_nairobi(request):
    return render(request, 'core/location.html', _location_context('nairobi'))

def loc_jkia(request):
    return render(request, 'core/location.html', _location_context('jkia'))

def loc_mombasa(request):
    return render(request, 'core/location.html', _location_context('mombasa'))

def loc_diani(request):
    return render(request, 'core/location.html', _location_context('diani'))


def about(request):
    """About page — trust, credibility, local SEO."""
    try:
        reviews = list(Review.objects.filter(is_published=True)[:3])
    except Exception:
        reviews = []
    return render(request, 'core/about.html', {
        'reviews':         reviews,
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    })


# ─────────────────────────────────────────────────────────────
#  BLOG (SEO-driven travel guides)
# ─────────────────────────────────────────────────────────────
BLOG_POSTS = {
    'self-drive-vs-with-driver-kenya': {
        'slug':        'self-drive-vs-with-driver-kenya',
        'title':       'Self-Drive vs With-Driver in Kenya: Which Should You Choose?',
        'meta_desc':   'Comparing self-drive and chauffeur-driven car rental in Kenya. Pricing, pros, cons and which option suits tourists, business travellers and Kenyan residents best.',
        'date':        'January 8, 2025',
        'read_time':   '6 min read',
        'category':    'Travel Guides',
        'hero_emoji':  '🚗',
        'excerpt':     'Choosing between self-drive and a chauffeured car is the biggest decision for any visitor to Kenya. Here\'s an honest, side-by-side breakdown to help you choose.',
    },
    'nairobi-to-maasai-mara-driving-guide': {
        'slug':        'nairobi-to-maasai-mara-driving-guide',
        'title':       'Driving from Nairobi to Maasai Mara: Complete 2025 Guide',
        'meta_desc':   'Step-by-step guide to driving from Nairobi to Maasai Mara National Reserve. Routes, fuel stops, accommodation, road conditions and what type of vehicle you need.',
        'date':        'January 12, 2025',
        'read_time':   '9 min read',
        'category':    'Safari Guides',
        'hero_emoji':  '🦁',
        'excerpt':     'The drive from Nairobi to the Maasai Mara is one of the most rewarding road trips in East Africa. Here\'s exactly what to expect — distances, road conditions, fuel stops and where to break the journey.',
    },
    'best-cars-for-kenyan-safari': {
        'slug':        'best-cars-for-kenyan-safari',
        'title':       'Best 4×4 Cars for a Kenyan Safari in 2025',
        'meta_desc':   'Which vehicle should you rent for a Kenyan safari? Comparison of Toyota Prado, Land Cruiser, Nissan X-Trail and Toyota Rav4 — pros, cons, fuel cost, comfort.',
        'date':        'January 18, 2025',
        'read_time':   '7 min read',
        'category':    'Safari Guides',
        'hero_emoji':  '🐘',
        'excerpt':     'Not every 4×4 is built for the Mara. Here\'s a frank comparison of the top safari rental vehicles in Kenya — what they cost, what they\'re great at, and what they\'re not.',
    },
    'driving-in-kenya-foreigners-guide': {
        'slug':        'driving-in-kenya-foreigners-guide',
        'title':       'Driving in Kenya as a Foreigner: Rules, Tips & What to Expect',
        'meta_desc':   'Practical guide for foreign visitors driving in Kenya. International driving permit, traffic rules, road etiquette, police checkpoints, fuel, parking and safety tips.',
        'date':        'February 2, 2025',
        'read_time':   '8 min read',
        'category':    'Travel Guides',
        'hero_emoji':  '🌍',
        'excerpt':     'Thinking of self-driving in Kenya? Here\'s the unfiltered guide every foreign visitor needs — from licence requirements to handling police checkpoints to surviving Nairobi traffic.',
    },
    'jkia-airport-arrival-survival-guide': {
        'slug':        'jkia-airport-arrival-survival-guide',
        'title':       'Arriving at JKIA Nairobi: A Complete Survival Guide for First-Timers',
        'meta_desc':   'First time landing at Jomo Kenyatta International Airport? Visa-on-arrival, SIM cards, Kenya shillings, taxis vs Uber vs car rental, and getting to your hotel safely.',
        'date':        'February 10, 2025',
        'read_time':   '7 min read',
        'category':    'Travel Guides',
        'hero_emoji':  '✈️',
        'excerpt':     'JKIA can feel chaotic if you\'ve never been. This is the step-by-step playbook locals wish every visitor had — from the immigration queue to leaving the airport without paying tourist prices.',
    },
    'two-week-kenya-itinerary-self-drive': {
        'slug':        'two-week-kenya-itinerary-self-drive',
        'title':       'The Perfect 2-Week Kenya Itinerary by Self-Drive (with Costs)',
        'meta_desc':   'A complete 14-day Kenya road trip: Nairobi, Maasai Mara, Lake Naivasha, Lake Nakuru, Mount Kenya, Diani Beach. Daily driving times, costs, accommodation and routing.',
        'date':        'February 18, 2025',
        'read_time':   '11 min read',
        'category':    'Travel Guides',
        'hero_emoji':  '🗺️',
        'excerpt':     'Two weeks, one rental car, half a country. This is the itinerary we\'d give a friend — Maasai Mara to Mount Kenya to Diani Beach, with real costs and the practical stuff guides skip.',
    },
    'kenya-honeymoon-road-trip-couples': {
        'slug':        'kenya-honeymoon-road-trip-couples',
        'title':       'A Kenya Honeymoon by Road: 10-Day Itinerary for Couples',
        'meta_desc':   'Romantic Kenya honeymoon by self-drive: Nairobi, Lake Naivasha, Maasai Mara safari and Diani Beach. Boutique stays, sunset moments, costs and the road trip route.',
        'date':        'March 4, 2025',
        'read_time':   '9 min read',
        'category':    'Couples Travel',
        'hero_emoji':  '💕',
        'excerpt':     'Kenya is one of the most underrated honeymoon destinations on the planet. Here\'s a 10-day road-trip itinerary for couples — bush, beach and a few quiet luxuries in between.',
    },
    'kenya-with-kids-family-safari-guide': {
        'slug':        'kenya-with-kids-family-safari-guide',
        'title':       'Kenya Family Safari with Kids: What to Expect & How to Plan',
        'meta_desc':   'Planning a Kenya safari with children? Honest guide to ages, vaccinations, baby seats, family-friendly lodges, driving distances and surviving long days in the bush with kids.',
        'date':        'March 14, 2025',
        'read_time':   '10 min read',
        'category':    'Family Travel',
        'hero_emoji':  '👨‍👩‍👧‍👦',
        'excerpt':     'Yes, you can take young kids on safari — and they\'ll love it. Here\'s the parent-tested playbook: which ages cope best, baby seat options, mid-range family lodges and how to keep everyone sane on long game drives.',
    },
}


def blog_index(request):
    """List all blog posts."""
    posts = list(BLOG_POSTS.values())
    return render(request, 'core/blog_index.html', {
        'posts':           posts,
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    })


def blog_post(request, slug):
    """Render a single blog post."""
    post = BLOG_POSTS.get(slug)
    if not post:
        from django.http import Http404
        raise Http404('Post not found')
    # Other posts for the "Read next" section
    others = [p for k, p in BLOG_POSTS.items() if k != slug][:2]
    return render(request, 'core/blog_post.html', {
        'post':            post,
        'others':          others,
        'whatsapp_number': getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
    })


def robots_txt(request):
    """robots.txt — tells search engines what to index."""
    site_url = getattr(settings, 'SITE_URL', 'https://yourdomain.com').rstrip('/')
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        "Disallow: /auth/\n"
        "Disallow: /dashboard/\n"
        "Disallow: /booking/submit/\n"
        "Disallow: /booking/resume/\n"
        "Disallow: /payments/\n"
        "\n"
        f"Sitemap: {site_url}/sitemap.xml\n"
    )
    return HttpResponse(content, content_type='text/plain')


# ─────────────────────────────────────────────────────────────
#  ERROR PAGES
# ─────────────────────────────────────────────────────────────
def error_404(request, exception=None):
    return render(request, 'core/404.html', status=404)

def error_500(request):
    return render(request, 'core/500.html', status=500)

def error_429(request):
    return render(request, 'core/429.html', status=429)