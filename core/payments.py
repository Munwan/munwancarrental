"""
Payment backends for Munwan Car Rental.

  PaystackBackend  – Card / Bank / Mobile Money / Apple Pay via Paystack
                     Inline popup (no card fields on our page — PCI-compliant)

Paystack handles ALL payment channels inside its popup — Visa/Mastercard,
M-Pesa, Apple Pay, bank transfer, USSD — so it is the only payment backend
the site needs. (The standalone PayPal and M-Pesa Daraja integrations were
removed: PayPal closed the business account, and Paystack already covers
M-Pesa, so the direct Daraja STK integration was redundant.)

SETUP
  pip install requests
  Add to .env:
    PAYSTACK_PUBLIC_KEY=pk_test_...            (or pk_live_... in production)
    PAYSTACK_SECRET_KEY=sk_test_...            (or sk_live_...)

Get Paystack keys from: https://dashboard.paystack.com/#/settings/developers
"""
import json
import logging

from django.conf import settings

logger = logging.getLogger('drivekenya.payments')


# ─────────────────────────────────────────────────────────────
#  Paystack
# ─────────────────────────────────────────────────────────────
class PaystackBackend:
    """
    Paystack Inline popup handles all card / bank / mobile-money details
    client-side. After the popup completes, the client sends back a `reference`.
    We verify that reference server-side using Paystack's verify endpoint.

    Flow:
      1. Frontend calls PaystackPop.setup({...}) with the booking reference
      2. User completes payment inside Paystack's iframe (never touches our server)
      3. Paystack callback returns a transaction reference
      4. Frontend POSTs that reference to our /payments/process/ endpoint
      5. PaystackBackend.verify() hits GET /transaction/verify/{reference}
      6. If status == 'success' and amount matches, we confirm the booking

    Docs: https://paystack.com/docs/api/transaction/
    """

    BASE_URL = 'https://api.paystack.co'

    @classmethod
    def _headers(cls):
        return {
            'Authorization': f'Bearer {getattr(settings, "PAYSTACK_SECRET_KEY", "")}',
            'Content-Type':  'application/json',
        }

    @classmethod
    def verify(cls, booking, reference: str) -> dict:
        """
        Verify a completed Paystack transaction server-side.
        `reference` is the transaction reference Paystack returned after the popup.

        Paystack amounts are in kobo / cents — they send back the amount in the
        smallest currency unit. Because we price in USD and Paystack typically
        processes KES for Kenyan merchants, we compare against total_kes × 100.
        """
        try:
            import requests

            if not reference:
                return {'success': False, 'ref': '', 'message': 'No transaction reference provided.', 'raw': {}}

            resp = requests.get(
                f'{cls.BASE_URL}/transaction/verify/{reference}',
                headers=cls._headers(),
                timeout=20,
            )
            data    = resp.json()
            payload = data.get('data', {}) or {}
            status  = payload.get('status', '')

            # Paystack sends amount in kobo (KES × 100) or the smallest unit of
            # whatever currency was charged. Compare to both KES and USD × 100.
            amount_minor = float(payload.get('amount', 0))
            currency     = (payload.get('currency') or '').upper()

            if currency == 'KES':
                expected_minor = float(booking.total_kes) * 100
            elif currency == 'USD':
                expected_minor = float(booking.total_usd) * 100
            else:
                expected_minor = float(booking.total_kes) * 100  # fallback

            if status == 'success' and amount_minor >= expected_minor * 0.99:
                logger.info('Paystack verified: %s → %s (%s %.2f)',
                            booking.reference, reference, currency, amount_minor / 100)
                return {
                    'success': True,
                    'ref':     reference,
                    'message': 'Payment verified successfully.',
                    'raw':     data,
                }
            else:
                logger.warning(
                    'Paystack verify failed: status=%s amount=%s expected=%s currency=%s',
                    status, amount_minor, expected_minor, currency,
                )
                return {
                    'success': False,
                    'ref':     reference,
                    'message': f'Payment not verified (status: {status}).',
                    'raw':     data,
                }

        except Exception as exc:
            logger.error('Paystack verify error for %s: %s', booking.reference, exc)
            return {'success': False, 'ref': '', 'message': str(exc), 'raw': {}}

    @classmethod
    def initialize(cls, booking) -> dict:
        """
        OPTIONAL: server-side initialize — returns a hosted checkout URL instead
        of using the inline popup. Not needed when using PaystackPop.setup() on
        the frontend, but useful if you want a redirect flow.

        Docs: https://paystack.com/docs/api/transaction/#initialize
        """
        try:
            import requests

            amount_kes = int(round(float(booking.total_kes) * 100))  # kobo

            payload = {
                'email':     booking.email,
                'amount':    amount_kes,
                'currency':  'KES',
                'reference': booking.reference,
                'callback_url': getattr(settings, 'SITE_URL', 'https://munwancarrental.com').rstrip('/')
                                + '/payments/paystack/callback/',
                'metadata': {
                    'booking_id':  booking.id,
                    'customer':    booking.full_name,
                    'phone':       booking.phone,
                    'vehicle':     booking.vehicle.name,
                    'custom_fields': [
                        {'display_name': 'Booking Ref', 'variable_name': 'booking_ref',
                         'value': booking.reference},
                        {'display_name': 'Vehicle', 'variable_name': 'vehicle',
                         'value': booking.vehicle.name},
                    ],
                },
                'channels': ['card', 'bank', 'ussd', 'mobile_money', 'bank_transfer'],
            }

            resp = requests.post(
                f'{cls.BASE_URL}/transaction/initialize',
                headers=cls._headers(),
                json=payload,
                timeout=20,
            )
            data           = resp.json()
            authorization_url = data.get('data', {}).get('authorization_url', '')
            access_code    = data.get('data', {}).get('access_code', '')
            return {
                'success':           bool(authorization_url),
                'authorization_url': authorization_url,
                'access_code':       access_code,
                'raw':               data,
            }
        except Exception as exc:
            logger.error('Paystack initialize error: %s', exc)
            return {'success': False, 'authorization_url': '', 'message': str(exc), 'raw': {}}