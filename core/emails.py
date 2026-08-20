"""
Email notifications for Munwan Car Rental.

Design philosophy:
- Feels like an email, not a webpage. Single column, plenty of white space.
- Quiet header (just the brand). No "Kenya · Premium Car Hire" tagline.
- Lean footer: WhatsApp, phone, email — no address, no hours, no copyright wall.
- Pre-payment emails LEAD with a clear "Complete Payment" call-to-action.
- Two emails after payment: booking confirmed + payment receipt (separate sends).

Functions:
  send_booking_received(booking)        – Customer "we received your booking" (Step 1)
  send_booking_confirmation(booking)    – Customer post-payment confirmation
  send_payment_receipt(booking)         – Customer payment receipt
  send_new_booking_admin_alert(booking) – Admin: new unpaid booking
  send_payment_admin_alert(booking)     – Admin: payment succeeded
  send_support_notification(ticket)     – Admin: new support ticket
"""
import html
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger('drivekenya.email')


# ════════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════════

def _admin_email():
    return getattr(settings, 'ADMIN_BOOKING_EMAIL',
                   getattr(settings, 'DEFAULT_FROM_EMAIL', 'info@munwancarrental.com'))


def _whatsapp_display():
    raw = getattr(settings, 'WHATSAPP_NUMBER', '254727745907').lstrip('+').strip()
    if raw.startswith('254') and len(raw) == 12:
        return f'+{raw[:3]} {raw[3:6]} {raw[6:9]} {raw[9:]}'
    return raw


def _whatsapp_link():
    raw = getattr(settings, 'WHATSAPP_NUMBER', '254727745907').lstrip('+').strip()
    return f'https://wa.me/{raw}'


def _info_email():
    return getattr(settings, 'ADMIN_BOOKING_EMAIL', 'info@munwancarrental.com')


def _site_url():
    return getattr(settings, 'SITE_URL', 'https://munwancarrental.com').rstrip('/')


# ════════════════════════════════════════════════════════════════════
#  Email Shell — minimal, email-native
# ════════════════════════════════════════════════════════════════════
#  Width capped at 560px (typical email max). Single column. Light header.
#  Lean footer with three contact methods. Inline CSS for client compatibility.
# ════════════════════════════════════════════════════════════════════

_EMAIL_SHELL = """\
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#F4F6FA;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#1F2937;-webkit-font-smoothing:antialiased;line-height:1.6;">

<div style="display:none;font-size:1px;color:#F4F6FA;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">{preheader}</div>

<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#F4F6FA;">
  <tr>
    <td align="center" style="padding:40px 16px;">

      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="560" style="max-width:560px;background:#FFFFFF;border-radius:8px;overflow:hidden;border:1px solid #E5E9F0;">

        <!-- Quiet header — just the brand -->
        <tr>
          <td style="padding:28px 32px 24px 32px;border-bottom:1px solid #EEF1F6;">
            <div style="font-size:18px;font-weight:700;letter-spacing:-0.01em;color:#0A0F1E;">
              Munwan<span style="color:#1565FF;">CarRental</span>
            </div>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            {body}
          </td>
        </tr>

        <!-- Lean footer: 3 contact methods, no address/hours/copyright wall -->
        <tr>
          <td style="padding:20px 32px 28px 32px;border-top:1px solid #EEF1F6;font-size:13px;color:#6B7280;line-height:1.7;">
            Questions? &nbsp;
            <a href="{whatsapp_link}" style="color:#1565FF;text-decoration:none;font-weight:500;">WhatsApp {whatsapp}</a> &nbsp;·&nbsp;
            <a href="mailto:{info_email}" style="color:#1565FF;text-decoration:none;font-weight:500;">{info_email}</a>
          </td>
        </tr>

      </table>

    </td>
  </tr>
</table>

</body>
</html>
"""


def _render_shell(*, title, preheader, body_html):
    return _EMAIL_SHELL.format(
        title=title,
        preheader=preheader,
        body=body_html,
        whatsapp=_whatsapp_display(),
        whatsapp_link=_whatsapp_link(),
        info_email=_info_email(),
    )


def _send_html(*, subject, to, html_body, text_body, preheader, attachments=None):
    try:
        full_html = _render_shell(title=subject, preheader=preheader, body_html=html_body)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to] if isinstance(to, str) else list(to),
        )
        msg.attach_alternative(full_html, 'text/html')
        for filename, content, mimetype in (attachments or []):
            msg.attach(filename, content, mimetype)
        msg.send(fail_silently=False)
        return True
    except Exception as exc:
        logger.warning('email send failed for "%s" → %s: %s', subject, to, exc)
        return False


# ════════════════════════════════════════════════════════════════════
#  Email body builders — minimal, email-native typography
# ════════════════════════════════════════════════════════════════════

def _h1(text):
    return f'<h1 style="font-size:22px;font-weight:700;color:#0A0F1E;margin:0 0 16px 0;line-height:1.3;">{text}</h1>'


def _p(text, color='#374151'):
    return f'<p style="font-size:15px;color:{color};line-height:1.6;margin:0 0 16px 0;">{text}</p>'


def _ref_pill(reference):
    """Inline reference code — looks like part of the prose, not a card."""
    return (
        f'<div style="margin:20px 0;padding:14px 18px;background:#F4F6FA;'
        f'border-left:3px solid #1565FF;border-radius:4px;">'
        f'<div style="font-size:12px;color:#6B7280;margin-bottom:4px;">Booking reference</div>'
        f'<div style="font-size:18px;font-weight:700;color:#0A0F1E;font-family:Menlo,Consolas,monospace;letter-spacing:0.02em;">{reference}</div>'
        f'</div>'
    )


class _SafeText(str):
    """
    Marks a string as pre-approved literal HTML for _details() — everything
    else gets escaped. Only use this for hardcoded markup we wrote (e.g. the
    "Paid" status badge below), never for anything derived from user input
    (company_name, transfer_destination, dropoff_location, etc. all flow
    through here unescaped otherwise and are attacker-controlled).
    """
    pass


def _esc(value):
    return value if isinstance(value, _SafeText) else html.escape(str(value))


def _details(rows):
    body = ''
    for label, value in rows:
        if value in (None, '', False):
            continue
        body += (
            f'<tr>'
            f'<td style="padding:10px 0;border-bottom:1px solid #EEF1F6;font-size:14px;color:#6B7280;width:40%;vertical-align:top;">{_esc(label)}</td>'
            f'<td style="padding:10px 0;border-bottom:1px solid #EEF1F6;font-size:14px;color:#0A0F1E;font-weight:500;text-align:right;">{_esc(value)}</td>'
            f'</tr>'
        )
    return f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:20px 0;">{body}</table>'


def _return_str(booking):
    """
    Format the return date/time, returning '— (one-way)' if not set
    (e.g. Airport Transfer bookings are one-way and don't have a return).
    """
    if booking.return_date and booking.return_time:
        return f'{booking.return_date} at {booking.return_time.strftime("%H:%M")}'
    return '— (one-way)'


def _is_transfer(booking):
    """True if this booking is an airport transfer."""
    return getattr(booking, 'hire_type', '') == 'transfer'


def _pricing(*, base, days, driver_fee, baby_seat, total_usd, total_kes):
    rows = (
        f'<tr>'
        f'<td style="padding:8px 0;font-size:14px;color:#6B7280;">Base ({days} day{"s" if days != 1 else ""})</td>'
        f'<td style="padding:8px 0;font-size:14px;color:#0A0F1E;text-align:right;">${base}</td>'
        f'</tr>'
    )
    if driver_fee and float(driver_fee) > 0:
        rows += (
            f'<tr>'
            f'<td style="padding:8px 0;font-size:14px;color:#6B7280;">Driver fee</td>'
            f'<td style="padding:8px 0;font-size:14px;color:#0A0F1E;text-align:right;">${driver_fee}</td>'
            f'</tr>'
        )
    if baby_seat:
        rows += (
            '<tr>'
            '<td style="padding:8px 0;font-size:14px;color:#6B7280;">Baby seat</td>'
            '<td style="padding:8px 0;font-size:14px;color:#0A0F1E;text-align:right;">$10.00</td>'
            '</tr>'
        )
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:18px 0;">'
        f'{rows}'
        f'<tr>'
        f'<td style="padding:14px 0 0 0;font-size:15px;font-weight:700;color:#0A0F1E;border-top:2px solid #0A0F1E;">Total</td>'
        f'<td style="padding:14px 0 0 0;font-size:18px;font-weight:700;color:#0A0F1E;text-align:right;border-top:2px solid #0A0F1E;">${total_usd}</td>'
        f'</tr>'
        f'<tr>'
        f'<td></td>'
        f'<td style="padding:2px 0 0 0;font-size:12px;color:#9CA3AF;text-align:right;">≈ KES {int(float(total_kes)):,}</td>'
        f'</tr>'
        f'</table>'
    )


def _cta(text, url):
    """Big primary action button."""
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:24px 0;">'
        f'<tr>'
        f'<td style="background:#1565FF;border-radius:6px;">'
        f'<a href="{url}" style="display:inline-block;padding:14px 28px;color:#FFFFFF;text-decoration:none;font-size:15px;font-weight:600;">{text}</a>'
        f'</td>'
        f'</tr>'
        f'</table>'
    )


def _section_label(text):
    return (
        f'<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;'
        f'color:#9CA3AF;margin:24px 0 4px 0;">{text}</div>'
    )


def _payment_url(booking):
    return f'{_site_url()}/?resume={booking.reference}#booking'


# ════════════════════════════════════════════════════════════════════
#  Customer Emails
# ════════════════════════════════════════════════════════════════════

def send_booking_received(booking):
    """
    Customer email at Step 1 — booking is reserved but not yet paid.
    LEADS with the payment call-to-action; booking details follow.
    For airport transfers, trip details show route/car-type instead of vehicle.
    """
    try:
        is_transfer = _is_transfer(booking)

        if is_transfer:
            # Airport transfer: route + car class. No specific vehicle name —
            # the customer chose a category (Mid-size, Luxury…) and we'll
            # assign whichever car is available on the day.
            route_label = booking.transfer_destination or booking.dropoff_location or '—'
            if booking.transfer_direction == 'TO':
                pickup_label = route_label
                drop_label   = 'JKIA'
            else:  # FROM (or default)
                pickup_label = 'JKIA'
                drop_label   = route_label
            details = _details([
                ('Trip',       'Airport Transfer (one-way)'),
                ('Pickup',     pickup_label),
                ('Drop-off',   drop_label),
                ('Zone',       booking.get_transfer_zone_display() if booking.transfer_zone else None),
                ('Car class',  booking.get_transfer_car_type_display() if booking.transfer_car_type else None),
                ('When',       f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
                ('Night fare', 'Yes (+$8 surcharge)' if booking.is_night_surcharge else None),
            ])
        else:
            is_extension = bool(getattr(booking, 'parent_booking_id', None))
            if is_extension:
                # Extension: customer is already with the car. Pickup
                # location and time don't apply — they're continuing from
                # their original return date. Show extension-specific info.
                parent_ref = booking.parent_booking.reference if booking.parent_booking else '—'
                details = _details([
                    ('Vehicle',         booking.vehicle.name),
                    ('Hire type',       'Extension of ' + parent_ref),
                    ('Driver',          'With driver' if booking.with_driver else 'Self drive'),
                    ('Extends through', _return_str(booking)),
                    ('Additional days', str(booking.days or '—')),
                ])
            else:
                details = _details([
                    ('Vehicle',   booking.vehicle.name),
                    ('Hire type', booking.get_hire_type_display()),
                    ('Driver',    'With driver' if booking.with_driver else 'Self drive'),
                    ('Pickup',    f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
                    ('Return',    _return_str(booking)),
                    ('Pickup at', booking.get_pickup_location_display()),
                    ('Hotel',     booking.hotel_address if booking.hotel_address else None),
                    ('Baby seat', 'Included (+$10)' if booking.baby_seat else None),
                ])

        pricing = _pricing(
            base=booking.base_price_usd, days=booking.days,
            driver_fee=booking.driver_fee_usd, baby_seat=booking.baby_seat,
            total_usd=booking.total_usd, total_kes=booking.total_kes,
        )

        # Top headline & lead paragraph — different for transfer vs rental
        if is_transfer:
            lead = (
                f'Your <strong>airport transfer</strong> is reserved. '
                f'To confirm, please complete payment of <strong>${booking.total_usd}</strong> '
                f'using the button below.'
            )
        elif (not is_transfer) and getattr(booking, 'parent_booking_id', None):
            # Extension reminder — the original booking IS already paid,
            # this email is about the additional days only.
            lead = (
                f'Your rental extension is reserved. '
                f'Please complete payment of <strong>${booking.total_usd}</strong> '
                f'for the additional days so we can confirm.'
            )
        else:
            lead = (
                f'We\'ve reserved your <strong>{booking.vehicle.name}</strong>. '
                f'To confirm your booking, complete payment of <strong>${booking.total_usd}</strong> '
                f'using the button below.'
            )

        body = (
            _h1(f'Hi {_esc(booking.first_name)}, please complete your payment')
            + _p(lead)
            + _cta('Complete Payment →', _payment_url(booking))
            + _ref_pill(booking.reference)
            + _section_label('Trip details')
            + details
            + _section_label('Pricing')
            + pricing
        )

        # Plain-text version
        if is_transfer:
            text = (
                f'Hi {booking.first_name},\n\n'
                f'Your airport transfer is reserved. Complete payment of ${booking.total_usd} to confirm:\n\n'
                f'{_payment_url(booking)}\n\n'
                f'Reference: {booking.reference}\n'
                f'Pickup: {booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}\n'
                f'Total:  ${booking.total_usd} (KES {int(float(booking.total_kes)):,})\n\n'
                f'WhatsApp: {_whatsapp_display()}\n'
                f'Email:    {_info_email()}\n'
            )
        else:
            text = (
                f'Hi {booking.first_name},\n\n'
                f'We\'ve reserved your {booking.vehicle.name}. '
                f'Complete payment of ${booking.total_usd} to confirm:\n\n'
                f'{_payment_url(booking)}\n\n'
                f'Reference: {booking.reference}\n'
                f'Pickup: {booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}\n'
                f'Return: {_return_str(booking)}\n'
                f'Total:  ${booking.total_usd} (KES {int(float(booking.total_kes)):,})\n\n'
                f'WhatsApp: {_whatsapp_display()}\n'
                f'Email:    {_info_email()}\n'
            )

        return _send_html(
            subject=f'Complete payment for booking {booking.reference}',
            to=booking.email,
            html_body=body,
            text_body=text,
            preheader=f'Complete ${booking.total_usd} payment to confirm your booking.',
        )
    except Exception:
        logger.exception('send_booking_received failed')
        return False


def send_booking_confirmation(booking):
    """Customer email after payment — booking is confirmed."""
    try:
        is_transfer = _is_transfer(booking)

        if is_transfer:
            route_label = booking.transfer_destination or booking.dropoff_location or '—'
            if booking.transfer_direction == 'TO':
                pickup_label, drop_label = route_label, 'JKIA'
            else:
                pickup_label, drop_label = 'JKIA', route_label
            details = _details([
                ('Trip',       'Airport Transfer (one-way)'),
                ('Pickup',     pickup_label),
                ('Drop-off',   drop_label),
                ('Zone',       booking.get_transfer_zone_display() if booking.transfer_zone else None),
                ('Car class',  booking.get_transfer_car_type_display() if booking.transfer_car_type else None),
                ('When',       f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
                ('Night fare', 'Yes (+$8 surcharge)' if booking.is_night_surcharge else None),
            ])
            lead_h1   = f'Transfer confirmed, {_esc(booking.first_name)}.'
            lead_p    = ('Your airport transfer is locked in. '
                         'We\'ll WhatsApp you with the driver\'s details before pickup.')
            preheader = f'Your airport transfer is locked in for {booking.pickup_date}.'
        else:
            is_extension = bool(getattr(booking, 'parent_booking_id', None))
            if is_extension:
                # Extension: customer is already with the car. Pickup
                # location and time don't apply — they're continuing from
                # their original return date. Show extension-specific info.
                parent_ref = booking.parent_booking.reference if booking.parent_booking else '—'
                details = _details([
                    ('Vehicle',         booking.vehicle.name),
                    ('Hire type',       'Extension of ' + parent_ref),
                    ('Driver',          'With driver' if booking.with_driver else 'Self drive'),
                    ('Extends through', _return_str(booking)),
                    ('Additional days', str(booking.days or '—')),
                ])
                lead_h1   = f'Extension confirmed, {_esc(booking.first_name)}.'
                lead_p    = (f'Your <strong>{booking.vehicle.name}</strong> rental '
                             f'has been extended to <strong>{_return_str(booking)}</strong>. '
                             f'Enjoy your additional days!')
                preheader = f'Your rental is extended to {_return_str(booking)}.'
            else:
                details = _details([
                    ('Vehicle',   booking.vehicle.name),
                    ('Hire type', booking.get_hire_type_display()),
                    ('Driver',    'With driver' if booking.with_driver else 'Self drive'),
                    ('Pickup',    f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
                    ('Return',    _return_str(booking)),
                    ('Pickup at', booking.get_pickup_location_display()),
                    ('Hotel',     booking.hotel_address if booking.hotel_address else None),
                    ('Baby seat', 'Included' if booking.baby_seat else None),
                ])
                lead_h1   = f'Booking confirmed, {_esc(booking.first_name)}.'
                lead_p    = (f'Your <strong>{booking.vehicle.name}</strong> is locked in. '
                             f'We\'ll WhatsApp you 24 hours before pickup with final details.')
                preheader = f'Your {booking.vehicle.name} is locked in for {booking.pickup_date}.'

        body = (
            _h1(lead_h1)
            + _p(lead_p)
            + _ref_pill(booking.reference)
            + _section_label('Confirmed details')
            + details
            + _section_label('Bring at pickup')
            + _p(
                'Passport or National ID, your driving licence (and IDP if visiting), '
                'and the card or M-Pesa number you paid with.',
                color='#374151',
            )
        )

        text_lines = [
            f'Hi {booking.first_name},',
            '',
            f'Your booking {booking.reference} is confirmed.',
            '',
        ]
        if is_transfer:
            text_lines += [
                f'Transfer: {booking.get_transfer_car_type_display()} ({booking.get_transfer_zone_display()})',
                f'When:     {booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}',
            ]
        else:
            text_lines += [
                f'Vehicle: {booking.vehicle.name}',
                f'Pickup:  {booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}',
                f'Return:  {_return_str(booking)}',
            ]
        text_lines += [
            '',
            'Bring at pickup: passport/ID, licence (and IDP if visiting), payment card/M-Pesa.',
            '',
            f'WhatsApp: {_whatsapp_display()}',
        ]
        text = '\n'.join(text_lines) + '\n'

        # Attach a PDF copy of this confirmation. If rendering fails, log it
        # but still send the email — the PDF is a bonus, not a blocker.
        attachments = []
        try:
            from .pdf_invoice import render_booking_confirmation_pdf
            pdf_bytes = render_booking_confirmation_pdf(booking)
            attachments.append(
                (f'booking-confirmation-{booking.reference}.pdf', pdf_bytes, 'application/pdf')
            )
        except Exception:
            logger.exception('Confirmation PDF render failed for %s — sending email without attachment', booking.reference)

        return _send_html(
            subject=f'Booking confirmed — {booking.reference}',
            to=booking.email,
            html_body=body,
            text_body=text,
            preheader=preheader,
            attachments=attachments,
        )
    except Exception:
        logger.exception('send_booking_confirmation failed')
        return False


def send_payment_receipt(booking):
    """Customer payment receipt — proof of payment."""
    try:
        is_transfer = _is_transfer(booking)
        pricing = _pricing(
            base=booking.base_price_usd, days=booking.days,
            driver_fee=booking.driver_fee_usd, baby_seat=booking.baby_seat,
            total_usd=booking.total_usd, total_kes=booking.total_kes,
        )

        if is_transfer:
            service_label = (
                f'Airport Transfer · {booking.get_transfer_car_type_display() or ""}'
                f' · {booking.get_transfer_zone_display() or ""}'
            ).strip(' ·')
            details = _details([
                ('Reference', booking.reference),
                ('Status',    _SafeText('<span style="color:#06A66D;">Paid</span>')),
                ('Method',    getattr(booking, 'payment_method', '') or 'Card'),
                ('Service',   service_label),
                ('When',      f'{booking.pickup_date} (one-way)'),
            ])
        else:
            details = _details([
                ('Reference', booking.reference),
                ('Status',    _SafeText('<span style="color:#06A66D;">Paid</span>')),
                ('Method',    getattr(booking, 'payment_method', '') or 'Card'),
                ('Vehicle',   booking.vehicle.name if booking.vehicle else '—'),
                ('Dates',     (f'{booking.pickup_date} → {booking.return_date}'
                               if booking.return_date
                               else f'{booking.pickup_date} (one-way)')),
            ])

        body = (
            _h1('Payment received')
            + _p(
                f'Hi {_esc(booking.first_name)}, we\'ve received <strong>${booking.total_usd}</strong> '
                f'for booking <strong>{booking.reference}</strong>. Keep this email as your receipt.'
            )
            + _section_label('Receipt')
            + details
            + _section_label('Amount')
            + pricing
        )

        text = (
            f'Hi {booking.first_name},\n\n'
            f'Payment received for booking {booking.reference}.\n'
            f'Total: ${booking.total_usd} (KES {int(float(booking.total_kes)):,})\n'
            f'Method: {getattr(booking, "payment_method", "Card") or "Card"}\n\n'
            f'WhatsApp: {_whatsapp_display()}\n'
        )

        return _send_html(
            subject=f'Payment receipt — {booking.reference}',
            to=booking.email,
            html_body=body,
            text_body=text,
            preheader=f'Receipt for ${booking.total_usd}.',
        )
    except Exception:
        logger.exception('send_payment_receipt failed')
        return False


# ════════════════════════════════════════════════════════════════════
#  Admin Emails
# ════════════════════════════════════════════════════════════════════

def send_new_booking_admin_alert(booking):
    """Admin: new unpaid booking submitted."""
    try:
        is_transfer = _is_transfer(booking)
        common = [
            ('Reference', booking.reference),
            ('Customer',  f'{booking.first_name} {booking.last_name}'),
            ('Email',     booking.email),
            ('Phone',     booking.phone),
            ('Hire type', booking.get_hire_type_display()),
        ]

        if is_transfer:
            route_label = booking.transfer_destination or booking.dropoff_location or '—'
            if booking.transfer_direction == 'TO':
                pickup_label, drop_label = route_label, 'JKIA'
            else:
                pickup_label, drop_label = 'JKIA', route_label
            specific = [
                ('Pickup',     pickup_label),
                ('Drop-off',   drop_label),
                ('Zone',       booking.get_transfer_zone_display() if booking.transfer_zone else None),
                ('Car class',  booking.get_transfer_car_type_display() if booking.transfer_car_type else None),
                ('When',       f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
                ('Night fare', 'Yes (+$8 surcharge)' if booking.is_night_surcharge else None),
            ]
        else:
            specific = [
                ('Vehicle',   booking.vehicle.name if booking.vehicle else '—'),
                ('Driver',    'With driver' if booking.with_driver else 'Self drive'),
                ('Pickup',    f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
                ('Return',    _return_str(booking)),
                ('Pickup at', booking.get_pickup_location_display()),
                ('Hotel',     booking.hotel_address if booking.hotel_address else None),
                ('Baby seat', 'Yes' if booking.baby_seat else None),
            ]

        details = _details(common + specific + [
            ('Total',  f'${booking.total_usd} (KES {int(float(booking.total_kes)):,})'),
            ('Status', booking.status),
        ])

        body = (
            _h1('New booking — payment pending')
            + _p('A customer just completed Step 1 and is on the payment page.')
            + _section_label('Booking')
            + details
        )

        if is_transfer:
            text = (
                f'NEW AIRPORT TRANSFER — {booking.reference}\n'
                f'{booking.first_name} {booking.last_name} <{booking.email}>\n'
                f'{booking.phone}\n'
                f'{booking.get_transfer_car_type_display()} · {booking.get_transfer_zone_display()} · ${booking.total_usd}\n'
            )
        else:
            text = (
                f'NEW BOOKING — {booking.reference}\n'
                f'{booking.first_name} {booking.last_name} <{booking.email}>\n'
                f'{booking.phone}\n'
                f'{booking.vehicle.name if booking.vehicle else "—"} · ${booking.total_usd}\n'
            )

        return _send_html(
            subject=f'New booking {booking.reference} — ${booking.total_usd}',
            to=_admin_email(),
            html_body=body,
            text_body=text,
            preheader=f'{_esc(booking.first_name)} {_esc(booking.last_name)} — ${booking.total_usd}',
        )
    except Exception:
        logger.exception('send_new_booking_admin_alert failed')
        return False


def send_payment_admin_alert(booking):
    """Admin: payment received."""
    try:
        details = _details([
            ('Reference', booking.reference),
            ('Customer',  f'{booking.first_name} {booking.last_name}'),
            ('Email',     booking.email),
            ('Phone',     booking.phone),
            ('Vehicle',   booking.vehicle.name),
            ('Method',    getattr(booking, 'payment_method', '') or 'Unknown'),
            ('Amount',    f'${booking.total_usd} (KES {int(float(booking.total_kes)):,})'),
        ])
        body = (
            _h1('Payment received')
            + _p('A customer has paid. The booking is now confirmed.')
            + _section_label('Payment')
            + details
        )
        text = (
            f'PAYMENT — {booking.reference}\n'
            f'${booking.total_usd} from {booking.first_name} {booking.last_name}\n'
        )
        return _send_html(
            subject=f'Payment received — {booking.reference} (${booking.total_usd})',
            to=_admin_email(),
            html_body=body,
            text_body=text,
            preheader=f'${booking.total_usd} from {_esc(booking.first_name)} {_esc(booking.last_name)}',
        )
    except Exception as exc:
        logger.exception('send_payment_admin_alert failed')
        return False


def send_support_notification(ticket):
    """Admin: new support ticket."""
    try:
        details = _details([
            ('From',    f'{ticket.name} <{ticket.email}>'),
            ('Phone',   getattr(ticket, 'phone', None)),
            ('Subject', ticket.subject),
        ])
        body = (
            _h1('New support enquiry')
            + _section_label('Sender')
            + details
            + _section_label('Message')
            + f'<div style="background:#F4F6FA;border-radius:6px;padding:16px 20px;font-size:14px;line-height:1.6;color:#0A0F1E;white-space:pre-wrap;">{ticket.message}</div>'
        )
        text = (
            f'SUPPORT — {ticket.subject}\n'
            f'{ticket.name} <{ticket.email}>\n\n'
            f'{ticket.message}\n'
        )
        return _send_html(
            subject=f'Support: {ticket.subject}',
            to=_admin_email(),
            html_body=body,
            text_body=text,
            preheader=f'{ticket.name}: {ticket.subject}',
        )
    except Exception as exc:
        logger.exception('send_support_notification failed')
        return False


# ════════════════════════════════════════════════════════════════════
#  Email OTP — sent during registration to verify the user's email
# ════════════════════════════════════════════════════════════════════

def send_otp_email(*, to_email: str, code: str, first_name: str = '') -> bool:
    """
    Sends a 6-digit verification code to the user during account registration.
    The OTP itself is the only thing the email needs to surface — keep it
    visually prominent and the rest minimal.
    """
    greeting = f'Hi {first_name},' if first_name else 'Hi,'
    body_html = f"""
      <h2 style="font-family:'Helvetica Neue',Arial,sans-serif;color:#0A0F1E;font-size:20px;margin:0 0 16px;">
        {greeting}
      </h2>
      <p style="font-family:'Helvetica Neue',Arial,sans-serif;color:#3A4259;font-size:15px;line-height:1.6;margin:0 0 24px;">
        Thank you for creating an account at Munwan Car Rental. To finish setting up your account, enter this 6-digit code on the verification page:
      </p>
      <div style="text-align:center;margin:32px 0;">
        <div style="display:inline-block;padding:18px 36px;background:#F4F6FA;border:2px dashed #1565FF;border-radius:12px;
                    font-family:'Courier New',monospace;font-size:36px;font-weight:800;letter-spacing:8px;color:#0A0F1E;">
          {code}
        </div>
      </div>
      <p style="font-family:'Helvetica Neue',Arial,sans-serif;color:#3A4259;font-size:14px;line-height:1.6;margin:0 0 8px;">
        This code expires in <strong>15 minutes</strong>.
      </p>
      <p style="font-family:'Helvetica Neue',Arial,sans-serif;color:#7A8298;font-size:13px;line-height:1.6;margin:24px 0 0;">
        If you didn't request this code, you can safely ignore this email — your address will NOT be added to our system.
      </p>
    """
    text_body = (
        f'{greeting}\n\n'
        f'Your Munwan Car Rental verification code: {code}\n\n'
        f'Enter this code on the verification page to complete your account setup.\n'
        f'This code expires in 15 minutes.\n\n'
        f"If you didn't request this, please ignore this email.\n"
    )
    try:
        return _send_html(
            subject=f'Your Munwan verification code: {code}',
            to=to_email,
            html_body=body_html,
            text_body=text_body,
            preheader=f'Your verification code is {code}. It expires in 15 minutes.',
        )
    except Exception as exc:
        logger.exception('send_otp_email failed for %s', to_email)
        return False


# ═════════════════════════════════════════════════════════════
#  INVOICE EMAIL (corporate hire)
# ═════════════════════════════════════════════════════════════
def send_invoice_email(booking):
    """
    Sends the corporate invoice email with PDF attached. Fires from
    booking_submit when hire_type=='corporate'. PDF is generated inline;
    if it fails we still send the email with a download link instead.
    """
    try:
        from .pdf_invoice import render_invoice_pdf
        from django.core.mail import EmailMessage
        from django.conf import settings

        invoice_no = booking.invoice_number or booking.reference
        due_str    = booking.invoice_due_date.strftime('%d %b %Y') if booking.invoice_due_date else '—'
        pickup_str = booking.pickup_date.strftime('%d %b %Y') if booking.pickup_date else '—'
        return_str = booking.return_date.strftime('%d %b %Y') if booking.return_date else '—'
        site_url   = _site_url()
        invoice_url = f"{site_url}/invoice/{booking.reference}/"
        pay_url     = f"{site_url}/?resume={booking.reference}"

        # Corporate-specific values. company_name (when set) is treated as
        # the billed party; the first/last name fields are the company
        # representative. Falls back gracefully if company_name is blank.
        is_corp        = (booking.hire_type == 'corporate')
        # company_name has no form-level cleaning (unlike first_name/last_name,
        # which are html.escape()'d in BookingStep1Form) — escape it here since
        # it's interpolated raw into _p() below, outside _details()'s escaping.
        # Wrapped as _SafeText so the _details() row further down (which also
        # calls _esc()) doesn't double-escape an already-escaped string.
        billed_party   = _SafeText(_esc(
            (booking.company_name or '').strip() or f'{booking.first_name} {booking.last_name}'))
        greeting_name  = booking.first_name or 'there'
        bill_to_label  = 'Company' if is_corp and booking.company_name else 'Billed to'

        # Build the HTML body using the same shell helpers as other emails
        body_html = ''.join([
            _h1('Corporate Hire — Pro-forma Invoice'),
            _p(
                f'Hi {greeting_name},'
                '<br/><br/>'
                + (f'This pro-forma invoice has been issued to <strong>{billed_party}</strong> '
                   'for the corporate hire booked below. ' if is_corp and booking.company_name
                   else 'Thank you for choosing Munwan Car Rental for your corporate hire. ')
                + f'A PDF copy is attached and is also available online below. '
                  f'Payment is due by <strong>{due_str}</strong> — one day before vehicle pickup.'
            ),
            _ref_pill(booking.reference),
            _details([
                ('Pro-forma invoice number',  invoice_no),
                (bill_to_label,     billed_party if is_corp and booking.company_name else None),
                ('KRA PIN',         booking.company_kra_pin if is_corp and booking.company_kra_pin else None),
                ('Representative',  f'{booking.first_name} {booking.last_name}' if is_corp and booking.company_name else None),
                ('Service',         booking.get_hire_type_display()),
                ('Vehicle',         booking.vehicle.name if booking.vehicle else 'TBD'),
                ('Pickup',          pickup_str),
                ('Return',          return_str),
                ('Days',            str(booking.days or '—')),
                ('Total (USD)',     f'${booking.total_usd}'),
                ('Total (KES)',     f'KES {booking.total_kes}' if booking.total_kes else None),
                ('Due date',        due_str),
            ]),
            _cta('💳 Pay Now', pay_url),
            _p(
                f'You can also <a href="{invoice_url}" '
                f'style="color:#1565FF;font-weight:700">view your pro-forma invoice online</a> '
                'at any time, or download the PDF copy attached.',
                color='#6B7280'
            ),
            _p(
                '<strong>Bank transfer:</strong> WhatsApp us at '
                f'<a href="{_whatsapp_link()}" style="color:#1565FF;font-weight:700">'
                f'{_whatsapp_display()}</a> for account details. '
                f'Quote booking reference <strong>{booking.reference}</strong> '
                f'or invoice number <strong>{invoice_no}</strong>.',
                color='#374151'
            ),
        ])

        html = _render_shell(
            title=f'Pro-forma Invoice {invoice_no} – Munwan Car Rental',
            preheader=f'Your corporate pro-forma invoice {invoice_no} – pay by {due_str}.',
            body_html=body_html,
        )

        # Plain-text fallback
        text_body = (
            f'PRO-FORMA INVOICE {invoice_no}\n'
            f'Munwan Car Rental\n\n'
            f'Hi {booking.first_name},\n\n'
            f'Thank you for choosing Munwan Car Rental for your corporate hire.\n'
            f'Your pro-forma invoice is attached as a PDF.\n\n'
            f'Booking ref: {booking.reference}\n'
            f'Vehicle: {booking.vehicle.name if booking.vehicle else "TBD"}\n'
            f'Pickup: {pickup_str}\n'
            f'Return: {return_str}\n'
            f'Days: {booking.days or "—"}\n'
            f'Total: ${booking.total_usd}\n'
            f'Due by: {due_str}\n\n'
            f'Pay online: {pay_url}\n'
            f'View pro-forma invoice: {invoice_url}\n\n'
            f'For bank transfer, WhatsApp us at {_whatsapp_display()}.\n'
            f'Quote {invoice_no} as the reference.\n\n'
            f'Thank you,\nMunwan Car Rental Team\n'
        )

        # Build the email message manually so we can attach the PDF.
        # _send_html() doesn't take attachments, so we use EmailMessage directly.
        msg = EmailMessage(
            subject=f'Pro-forma Invoice {invoice_no} – Munwan Car Rental',
            body=text_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None) or _info_email(),
            to=[booking.email],
            reply_to=[_info_email()],
        )
        # Attach an HTML alternative
        msg.content_subtype = 'plain'   # primary is plain; html added below
        msg.attach_alternative = None    # disable accidental usage
        # Use EmailMultiAlternatives pattern: switch class for HTML support
        from django.core.mail import EmailMultiAlternatives
        msg = EmailMultiAlternatives(
            subject=f'Pro-forma Invoice {invoice_no} – Munwan Car Rental',
            body=text_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None) or _info_email(),
            to=[booking.email],
            reply_to=[_info_email()],
        )
        msg.attach_alternative(html, 'text/html')

        # Attach the PDF. If rendering fails, log it but still send the email.
        try:
            pdf_bytes = render_invoice_pdf(booking)
            msg.attach(f'proforma-invoice-{invoice_no}.pdf', pdf_bytes, 'application/pdf')
        except Exception:
            logger.exception('Invoice PDF attach failed for %s — sending email without attachment', invoice_no)

        msg.send(fail_silently=False)
        logger.info('Invoice email sent for %s to %s', invoice_no, booking.email)
        return True

    except Exception:
        logger.exception('send_invoice_email failed for booking %s', getattr(booking, 'reference', '?'))
        return False