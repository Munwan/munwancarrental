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


def _send_html(*, subject, to, html_body, text_body, preheader):
    try:
        full_html = _render_shell(title=subject, preheader=preheader, body_html=html_body)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to] if isinstance(to, str) else list(to),
        )
        msg.attach_alternative(full_html, 'text/html')
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


def _details(rows):
    body = ''
    for label, value in rows:
        if value in (None, '', False):
            continue
        body += (
            f'<tr>'
            f'<td style="padding:10px 0;border-bottom:1px solid #EEF1F6;font-size:14px;color:#6B7280;width:40%;vertical-align:top;">{label}</td>'
            f'<td style="padding:10px 0;border-bottom:1px solid #EEF1F6;font-size:14px;color:#0A0F1E;font-weight:500;text-align:right;">{value}</td>'
            f'</tr>'
        )
    return f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:20px 0;">{body}</table>'


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
    """
    try:
        details = _details([
            ('Vehicle',   booking.vehicle.name),
            ('Hire type', booking.get_hire_type_display()),
            ('Driver',    'With driver' if booking.with_driver else 'Self drive'),
            ('Pickup',    f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
            ('Return',    f'{booking.return_date} at {booking.return_time.strftime("%H:%M")}'),
            ('Pickup at', booking.get_pickup_location_display()),
            ('Hotel',     booking.hotel_address if booking.hotel_address else None),
            ('Baby seat', 'Included (+$10)' if booking.baby_seat else None),
        ])
        pricing = _pricing(
            base=booking.base_price_usd, days=booking.days,
            driver_fee=booking.driver_fee_usd, baby_seat=booking.baby_seat,
            total_usd=booking.total_usd, total_kes=booking.total_kes,
        )

        body = (
            _h1(f'Hi {booking.first_name}, please complete your payment')
            + _p(
                f'We\'ve reserved your <strong>{booking.vehicle.name}</strong>. '
                f'To confirm your booking, complete payment of <strong>${booking.total_usd}</strong> '
                f'using the button below.'
            )
            + _cta('Complete Payment →', _payment_url(booking))
            + _ref_pill(booking.reference)
            + _section_label('Trip details')
            + details
            + _section_label('Pricing')
            + pricing
        )

        text = (
            f'Hi {booking.first_name},\n\n'
            f'We\'ve reserved your {booking.vehicle.name}. '
            f'Complete payment of ${booking.total_usd} to confirm:\n\n'
            f'{_payment_url(booking)}\n\n'
            f'Reference: {booking.reference}\n'
            f'Pickup: {booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}\n'
            f'Return: {booking.return_date} at {booking.return_time.strftime("%H:%M")}\n'
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
    except Exception as exc:
        logger.warning('send_booking_received failed: %s', exc)
        return False


def send_booking_confirmation(booking):
    """Customer email after payment — booking is confirmed."""
    try:
        details = _details([
            ('Vehicle',   booking.vehicle.name),
            ('Hire type', booking.get_hire_type_display()),
            ('Driver',    'With driver' if booking.with_driver else 'Self drive'),
            ('Pickup',    f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
            ('Return',    f'{booking.return_date} at {booking.return_time.strftime("%H:%M")}'),
            ('Pickup at', booking.get_pickup_location_display()),
            ('Hotel',     booking.hotel_address if booking.hotel_address else None),
            ('Baby seat', 'Included' if booking.baby_seat else None),
        ])

        body = (
            _h1(f'Booking confirmed, {booking.first_name}.')
            + _p(
                f'Your <strong>{booking.vehicle.name}</strong> is locked in. '
                f'We\'ll WhatsApp you 24 hours before pickup with final details.'
            )
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

        text = (
            f'Hi {booking.first_name},\n\n'
            f'Your booking {booking.reference} is confirmed.\n\n'
            f'Vehicle: {booking.vehicle.name}\n'
            f'Pickup:  {booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}\n'
            f'Return:  {booking.return_date} at {booking.return_time.strftime("%H:%M")}\n\n'
            f'Bring at pickup: passport/ID, licence (and IDP if visiting), payment card/M-Pesa.\n\n'
            f'WhatsApp: {_whatsapp_display()}\n'
        )

        return _send_html(
            subject=f'Booking confirmed — {booking.reference}',
            to=booking.email,
            html_body=body,
            text_body=text,
            preheader=f'Your {booking.vehicle.name} is locked in for {booking.pickup_date}.',
        )
    except Exception as exc:
        logger.warning('send_booking_confirmation failed: %s', exc)
        return False


def send_payment_receipt(booking):
    """Customer payment receipt — proof of payment."""
    try:
        pricing = _pricing(
            base=booking.base_price_usd, days=booking.days,
            driver_fee=booking.driver_fee_usd, baby_seat=booking.baby_seat,
            total_usd=booking.total_usd, total_kes=booking.total_kes,
        )
        details = _details([
            ('Reference',  booking.reference),
            ('Status',     '<span style="color:#06A66D;">Paid</span>'),
            ('Method',     getattr(booking, 'payment_method', '') or 'Card'),
            ('Vehicle',    booking.vehicle.name),
            ('Dates',      f'{booking.pickup_date} → {booking.return_date}'),
        ])

        body = (
            _h1('Payment received')
            + _p(
                f'Hi {booking.first_name}, we\'ve received <strong>${booking.total_usd}</strong> '
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
    except Exception as exc:
        logger.warning('send_payment_receipt failed: %s', exc)
        return False


# ════════════════════════════════════════════════════════════════════
#  Admin Emails
# ════════════════════════════════════════════════════════════════════

def send_new_booking_admin_alert(booking):
    """Admin: new unpaid booking submitted."""
    try:
        details = _details([
            ('Reference', booking.reference),
            ('Customer',  f'{booking.first_name} {booking.last_name}'),
            ('Email',     booking.email),
            ('Phone',     booking.phone),
            ('Vehicle',   booking.vehicle.name),
            ('Hire type', booking.get_hire_type_display()),
            ('Driver',    'With driver' if booking.with_driver else 'Self drive'),
            ('Pickup',    f'{booking.pickup_date} at {booking.pickup_time.strftime("%H:%M")}'),
            ('Return',    f'{booking.return_date} at {booking.return_time.strftime("%H:%M")}'),
            ('Pickup at', booking.get_pickup_location_display()),
            ('Hotel',     booking.hotel_address if booking.hotel_address else None),
            ('Baby seat', 'Yes' if booking.baby_seat else None),
            ('Total',     f'${booking.total_usd} (KES {int(float(booking.total_kes)):,})'),
            ('Status',    booking.status),
        ])
        body = (
            _h1('New booking — payment pending')
            + _p('A customer just completed Step 1 and is on the payment page.')
            + _section_label('Booking')
            + details
        )
        text = (
            f'NEW BOOKING — {booking.reference}\n'
            f'{booking.first_name} {booking.last_name} <{booking.email}>\n'
            f'{booking.phone}\n'
            f'{booking.vehicle.name} · ${booking.total_usd}\n'
        )
        return _send_html(
            subject=f'New booking {booking.reference} — ${booking.total_usd}',
            to=_admin_email(),
            html_body=body,
            text_body=text,
            preheader=f'{booking.first_name} {booking.last_name} — ${booking.total_usd}',
        )
    except Exception as exc:
        logger.warning('send_new_booking_admin_alert failed: %s', exc)
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
            preheader=f'${booking.total_usd} from {booking.first_name} {booking.last_name}',
        )
    except Exception as exc:
        logger.warning('send_payment_admin_alert failed: %s', exc)
        return False


def send_support_notification(ticket):
    """Admin: new support ticket."""
    try:
        details = _details([
            ('From',    f'{ticket.name} &lt;{ticket.email}&gt;'),
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
        logger.warning('send_support_notification failed: %s', exc)
        return False