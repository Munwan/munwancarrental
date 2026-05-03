"""
Payment backends for Munwan Car Rental.

  PaystackBackend  – Card / Bank / Mobile Money via Paystack Inline popup
                     (no card fields on our page — PCI-compliant)
  MpesaBackend     – Direct Safaricom Daraja STK Push (native Kenyan M-Pesa)
  PayPalBackend    – PayPal Orders API (international customers)

SETUP
  pip install requests
  Add to .env:
    PAYSTACK_PUBLIC_KEY=pk_test_...            (or pk_live_... in production)
    PAYSTACK_SECRET_KEY=sk_test_...            (or sk_live_...)
    PAYPAL_CLIENT_ID / PAYPAL_SECRET
    MPESA_CONSUMER_KEY / MPESA_CONSUMER_SECRET / MPESA_SHORTCODE / MPESA_PASSKEY

Get Paystack keys from: https://dashboard.paystack.com/#/settings/developers
"""
import base64
import json
import logging
from datetime import datetime

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


# ─────────────────────────────────────────────────────────────
#  PayPal
# ─────────────────────────────────────────────────────────────
class PayPalBackend:
    BASE_URLS = {
        'sandbox':    'https://api-m.sandbox.paypal.com',
        'production': 'https://api-m.paypal.com',
        'live':       'https://api-m.paypal.com',  # alias — PayPal's dashboard says "live"
    }

    @classmethod
    def _base_url(cls):
        # Accept both "production" and "live" — PayPal's dashboard says "live"
        # while many integrations historically use "production". Either works.
        mode = (getattr(settings, 'PAYPAL_MODE', 'sandbox') or 'sandbox').lower().strip()
        return cls.BASE_URLS.get(mode, cls.BASE_URLS['sandbox'])

    @classmethod
    def _get_token(cls) -> str:
        import requests
        resp = requests.post(
            f'{cls._base_url()}/v1/oauth2/token',
            headers={'Accept': 'application/json'},
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_SECRET),
            data={'grant_type': 'client_credentials'},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    @classmethod
    def capture_order(cls, booking, paypal_order_id: str) -> dict:
        try:
            import requests
            token = cls._get_token()
            resp  = requests.post(
                f'{cls._base_url()}/v2/checkout/orders/{paypal_order_id}/capture',
                headers={
                    'Content-Type':  'application/json',
                    'Authorization': f'Bearer {token}',
                },
                timeout=20,
            )
            data = resp.json()
            if data.get('status') == 'COMPLETED':
                txn_id = data['purchase_units'][0]['payments']['captures'][0]['id']
                logger.info('PayPal capture succeeded: %s → %s',
                            booking.reference, txn_id)
                return {'success': True, 'ref': txn_id,
                        'message': 'PayPal payment completed', 'raw': data}
            else:
                return {'success': False, 'ref': paypal_order_id,
                        'message': f'PayPal status: {data.get("status")}', 'raw': data}
        except Exception as exc:
            logger.error('PayPal capture error for %s: %s', booking.reference, exc)
            return {'success': False, 'ref': '', 'message': str(exc), 'raw': {}}

    @classmethod
    def create_order(cls, booking) -> dict:
        try:
            import requests
            token   = cls._get_token()
            payload = {
                'intent': 'CAPTURE',
                'purchase_units': [{
                    'reference_id': booking.reference,
                    'description':  f'Munwan Car Rental – {booking.vehicle.name}',
                    'amount': {
                        'currency_code': 'USD',
                        'value':         str(booking.total_usd),
                    },
                }],
            }
            resp = requests.post(
                f'{cls._base_url()}/v2/checkout/orders',
                headers={
                    'Content-Type':  'application/json',
                    'Authorization': f'Bearer {token}',
                },
                json=payload,
                timeout=20,
            )
            data     = resp.json()
            order_id = data.get('id')
            return {'success': bool(order_id), 'order_id': order_id, 'raw': data}
        except Exception as exc:
            logger.error('PayPal create_order error: %s', exc)
            return {'success': False, 'order_id': None,
                    'message': str(exc), 'raw': {}}


# ─────────────────────────────────────────────────────────────
#  M-Pesa (Daraja API – STK Push)
# ─────────────────────────────────────────────────────────────
class MpesaBackend:
    BASE_URLS = {
        'sandbox':    'https://sandbox.safaricom.co.ke',
        'production': 'https://api.safaricom.co.ke',
    }

    @classmethod
    def _base_url(cls):
        return cls.BASE_URLS.get(
            getattr(settings, 'MPESA_ENV', 'sandbox'),
            cls.BASE_URLS['sandbox'])

    @classmethod
    def _get_token(cls) -> str:
        import requests
        credentials = base64.b64encode(
            f'{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}'.encode()
        ).decode()
        resp = requests.get(
            f'{cls._base_url()}/oauth/v1/generate?grant_type=client_credentials',
            headers={'Authorization': f'Basic {credentials}'},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    @classmethod
    def _generate_password(cls):
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        raw       = f'{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}'
        password  = base64.b64encode(raw.encode()).decode()
        return password, timestamp

    @classmethod
    def stk_push(cls, booking, phone: str) -> dict:
        try:
            import requests
            phone = phone.strip().replace(' ', '').replace('-', '')
            if phone.startswith('+'): phone = phone[1:]
            if phone.startswith('0'): phone = '254' + phone[1:]

            token              = cls._get_token()
            password, timestamp = cls._generate_password()
            amount             = max(1, int(float(booking.total_kes)))

            payload = {
                'BusinessShortCode': settings.MPESA_SHORTCODE,
                'Password':          password,
                'Timestamp':         timestamp,
                'TransactionType':   'CustomerPayBillOnline',
                'Amount':            amount,
                'PartyA':            phone,
                'PartyB':            settings.MPESA_SHORTCODE,
                'PhoneNumber':       phone,
                'CallBackURL':       settings.MPESA_CALLBACK_URL,
                'AccountReference':  booking.reference,
                'TransactionDesc':   f'Munwan Car Rental {booking.reference}',
            }
            resp = requests.post(
                f'{cls._base_url()}/mpesa/stkpush/v1/processrequest',
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type':  'application/json',
                },
                json=payload,
                timeout=20,
            )
            data        = resp.json()
            checkout_id = data.get('CheckoutRequestID', '')

            if data.get('ResponseCode') == '0':
                logger.info('M-Pesa STK push sent: %s → %s',
                            booking.reference, checkout_id)
                return {
                    'success': True,
                    'ref':     checkout_id,
                    'message': 'STK push sent. Please check your phone.',
                    'raw':     data,
                }
            else:
                logger.warning('M-Pesa STK push failed: %s', data)
                return {
                    'success': False,
                    'ref':     checkout_id,
                    'message': data.get('errorMessage', 'M-Pesa push failed'),
                    'raw':     data,
                }
        except Exception as exc:
            logger.error('M-Pesa error for %s: %s', booking.reference, exc)
            return {'success': False, 'ref': '', 'message': str(exc), 'raw': {}}

    @classmethod
    def handle_callback(cls, payload: dict) -> dict:
        try:
            body        = payload.get('Body', {}).get('stkCallback', {})
            result_code = body.get('ResultCode')
            checkout_id = body.get('CheckoutRequestID', '')
            if result_code == 0:
                items = body.get('CallbackMetadata', {}).get('Item', [])
                meta  = {item['Name']: item.get('Value') for item in items}
                return {
                    'success':     True,
                    'checkout_id': checkout_id,
                    'mpesa_code':  meta.get('MpesaReceiptNumber', ''),
                    'raw':         payload,
                }
            else:
                return {
                    'success':     False,
                    'checkout_id': checkout_id,
                    'message':     body.get('ResultDesc', 'Payment failed'),
                    'raw':         payload,
                }
        except Exception as exc:
            logger.error('M-Pesa callback parse error: %s', exc)
            return {'success': False, 'message': str(exc), 'raw': payload}