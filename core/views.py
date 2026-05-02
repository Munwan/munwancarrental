import json
import logging
import traceback

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
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .emails import send_booking_confirmation, send_support_notification
from .forms import (
    BookingStep1Form, BookingPaymentForm,
    CheckBookingForm, LoginForm, RegisterForm, SupportForm,
)
from .middleware import get_client_ip
from .models import Booking, PaymentLog, Review, SupportTicket, Vehicle
from .payments import PaystackBackend, MpesaBackend, PayPalBackend

logger = logging.getLogger('drivekenya.views')


def _json_error(message, status=400):
    return JsonResponse({'ok': False, 'error': message}, status=status)


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

    context = {
        'vehicles':           vehicles,
        'reviews':            reviews,
        'paystack_pk':        getattr(settings, 'PAYSTACK_PUBLIC_KEY', ''),
        'paypal_client_id':   getattr(settings, 'PAYPAL_CLIENT_ID', ''),
        'whatsapp_number':    getattr(settings, 'WHATSAPP_NUMBER', '254727745907'),
        'pickup_choices':     Booking.PICKUP_LOCATION_CHOICES,
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
#  BOOKING SUBMIT  (Step 1)
# ─────────────────────────────────────────────────────────────
@require_POST
def booking_submit(request):
    try:
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
        if existing_ref:
            try:
                booking = Booking.objects.get(
                    reference=existing_ref,
                    payment_status='unpaid',
                    email__iexact=cd['email'],  # only the owner can edit
                )
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
        booking.with_driver      = with_driver
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
        booking.save()

        # Email admin about new booking immediately. The CUSTOMER reminder
        # ("Complete Payment") is delayed: it fires from the
        # management command `send_payment_reminders` after 1 hour, ONLY if
        # the booking is still unpaid. If they pay within the hour, no email.
        # Fire admin email in a background thread so the HTTP response returns
        # immediately — SMTP can take 1-3 seconds and would block the user.
        try:
            import threading
            from .emails import send_new_booking_admin_alert
            threading.Thread(
                target=send_new_booking_admin_alert,
                args=(booking,),
                daemon=True,
            ).start()
        except Exception as e:
            logger.warning('Booking-creation admin email thread failed: %s', e)

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
                    logger.warning('Account creation failed: %s', exc)

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
    Only unpaid bookings are returned via the public reference path.
    """
    reference = (request.GET.get('reference') or '').strip()
    b = None

    if reference:
        # Public resume: only allow unpaid bookings
        try:
            b = Booking.objects.get(reference=reference, payment_status='unpaid')
            request.session['pending_booking_id'] = b.id
        except Booking.DoesNotExist:
            return _json_error('Booking not found or already paid.', 404)
    else:
        booking_id = request.session.get('pending_booking_id')
        if not booking_id:
            return _json_error('No pending booking.', 404)
        try:
            b = Booking.objects.get(id=booking_id)
        except Booking.DoesNotExist:
            return _json_error('Booking not found.', 404)

    try:
        return JsonResponse({
            'ok':          True,
            'reference':   b.reference,
            'vehicle':     b.vehicle.name,
            'days':        b.days,
            'total_usd':   str(b.total_usd),
            'total_kes':   str(b.total_kes),
            'total_eur':   str(b.total_eur),
            'base_price':  str(b.base_price_usd),
            'driver_fee':  str(b.driver_fee_usd),
            'with_driver': b.with_driver,
            'baby_seat':   b.baby_seat,
            'baby_seat_fee': '10.00' if b.baby_seat else '0.00',
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


# ─────────────────────────────────────────────────────────────
#  PAYMENT PROCESS  (Step 2)
# ─────────────────────────────────────────────────────────────
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
                import threading
                from .emails import send_payment_receipt, send_payment_admin_alert
                for fn in (send_booking_confirmation, send_payment_receipt, send_payment_admin_alert):
                    threading.Thread(target=fn, args=(booking,), daemon=True).start()
            except Exception as e:
                logger.warning('Post-payment email threads failed: %s', e)
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
                booking = Booking.objects.filter(reference=reference).first()
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
                        import threading
                        from .emails import (send_booking_confirmation,
                                              send_payment_receipt,
                                              send_payment_admin_alert)
                        for fn in (send_booking_confirmation, send_payment_receipt, send_payment_admin_alert):
                            threading.Thread(target=fn, args=(booking,), daemon=True).start()
                    except Exception as e:
                        logger.warning('Webhook email threads failed for %s: %s', reference, e)
                logger.info('Paystack webhook confirmed booking: %s', reference)

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
            return JsonResponse({
                'ok':          True,
                'reference':   b.reference,
                'vehicle':     b.vehicle.name,
                'pickup':      b.get_pickup_location_display(),
                'pickup_date': b.pickup_date.strftime('%d %b %Y'),
                'return_date': b.return_date.strftime('%d %b %Y'),
                'status':      b.get_status_display(),
                'payment':     b.get_payment_status_display(),
                'total_usd':   str(b.total_usd),
                'total_kes':   str(b.total_kes),
                'with_driver': b.with_driver,
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


def auth_register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        # Explicit backend — required when AUTHENTICATION_BACKENDS has > 1 entry.
        # Without this, Django raises ValueError at this point even though the
        # user has been saved successfully.
        login(request, user, backend='core.auth_backends.EmailOrUsernameBackend')
        messages.success(request, f'Welcome, {user.first_name}! Your account is ready.')
        return redirect('dashboard')
    return render(request, 'core/auth/register.html', {'form': form})


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
        logger.warning('Orphan claim skipped: %s', exc)

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

    active_bookings = [b for b in all_bookings
                       if b.return_date >= today
                       and b.status not in ('completed', 'cancelled')]
    past_bookings = [b for b in all_bookings
                     if b.return_date < today
                     or b.status in ('completed', 'cancelled')]

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
                except Exception as e:
                    logger.warning('Support email failed: %s', e)
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