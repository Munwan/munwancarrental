# DriveKenya – Django Car Hire Website

A full-featured Django car hire platform built for Kenya.

---

## Quick Start

### 1. Prerequisites
- Python 3.10+
- pip

### 2. Create & activate virtual environment
```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
# Edit .env and fill in your keys
```

### 5. Run migrations
```bash
python manage.py migrate
```

### 6. Create superuser (admin)
```bash
python manage.py createsuperuser
```

### 7. Seed vehicles & reviews
```bash
python manage.py seed_data
```

### 8. Add your car images
Place your custom images in:
```
media/cars/
```
Name them however you like. Then in the Django Admin (http://localhost:8000/admin/),
go to **Core → Vehicles**, edit each vehicle, and upload its image.

Also add a **hero background image** at:
```
static/images/hero-bg.jpg
```
(any high-quality driving / road scene, landscape orientation, 1920×1080+)

### 9. Run the dev server
```bash
python manage.py runserver
```
Visit: http://localhost:8000

---

## Payment Setup

### Stripe (Card payments)
1. Create account at https://stripe.com
2. Get your keys from https://dashboard.stripe.com/apikeys
3. Add to `.env`:
   - `STRIPE_PUBLISHABLE_KEY=pk_test_...`
   - `STRIPE_SECRET_KEY=sk_test_...`
4. For webhooks (local testing): `stripe listen --forward-to localhost:8000/payments/stripe/webhook/`
5. Add webhook secret to `.env`: `STRIPE_WEBHOOK_SECRET=whsec_...`

### PayPal
1. Create app at https://developer.paypal.com/dashboard/
2. Get Client ID and Secret
3. Add to `.env`
4. Switch `PAYPAL_MODE=live` for production

### M-Pesa (Daraja API)
1. Register at https://developer.safaricom.co.ke/
2. Create an app and get Consumer Key & Secret
3. For sandbox: use shortcode `174379` and test passkey
4. Set `MPESA_CALLBACK_URL` to a publicly accessible URL
   (use ngrok for local testing: `ngrok http 8000`)
5. Switch `MPESA_ENV=production` for live

---

## Admin Panel
Visit: http://localhost:8000/admin/

- Manage vehicles, set images, pricing, availability
- View all bookings and payment status
- Publish customer reviews
- Handle support tickets

---

## Image Folder Structure
```
drivekenya/
├── media/
│   └── cars/           ← upload car images here (via admin or directly)
└── static/
    └── images/
        ├── hero-bg.jpg  ← hero section background
        └── cars/
            └── placeholder.jpg  ← fallback if no image set
```

---

## Production Checklist
- [ ] Set `DEBUG=False`
- [ ] Set a strong `DJANGO_SECRET_KEY`
- [ ] Set `ALLOWED_HOSTS` to your domain
- [ ] Switch to PostgreSQL (see `settings.py` comments)
- [ ] Configure real SMTP email
- [ ] Run `python manage.py collectstatic`
- [ ] Set live keys for Stripe, PayPal, M-Pesa
- [ ] Set `PAYPAL_MODE=live` and `MPESA_ENV=production`
- [ ] Use gunicorn + nginx in production
- [ ] Enable HTTPS (Let's Encrypt)

---

## Project Structure
```
drivekenya/
├── core/
│   ├── admin.py          Admin registrations
│   ├── emails.py         Email notifications
│   ├── forms.py          All forms + validation
│   ├── middleware.py      Rate limiting
│   ├── models.py         Vehicle, Booking, Review, etc.
│   ├── payments.py       Stripe, PayPal, M-Pesa backends
│   ├── urls.py           URL routing
│   ├── views.py          All views
│   ├── management/
│   │   └── commands/
│   │       └── seed_data.py   Initial data seeder
│   └── templates/core/
│       ├── base.html          Base layout
│       ├── home.html          Landing page
│       ├── auth/
│       │   ├── login.html
│       │   └── register.html
│       ├── dashboard.html     Customer bookings
│       ├── support.html       Contact form
│       ├── check_booking.html
│       └── emails/
│           └── booking_confirmation.txt
├── static/
│   ├── css/main.css
│   ├── js/main.js
│   └── images/
├── media/
│   └── cars/
├── drivekenya/
│   ├── settings.py
│   └── urls.py
├── requirements.txt
├── .env.example
└── manage.py
```
