import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils import timezone


# ─────────────────────────────────────────────────────────────
#  VEHICLE
# ─────────────────────────────────────────────────────────────
class Vehicle(models.Model):
    CATEGORY_CHOICES = [
        ('economy',   'Economy'),
        ('mid',       'Mid-Range'),
        ('suv',       'SUV / 4×4'),
        ('luxury',    'Luxury'),
        ('van',       'Van / Minibus'),
        ('safari',    'Safari Ready'),
    ]
    BADGE_CHOICES = [
        ('pop',  'Most Popular'),
        ('eco',  'Economy'),
        ('lux',  'Luxury'),
        ('saf',  'Safari Ready'),
        ('van',  'Group Travel'),
        ('mid',  'Mid-Range'),
        ('exec', 'Executive'),
    ]
    # Airport-transfer car class. Used by /airport-transfer/ pricing.
    # Leave blank ('') for a vehicle that should NOT appear in airport
    # transfer at all (e.g. a heavy 4x4 with 80L diesel tank wouldn't be
    # economical for a 30km airport run).
    TRANSFER_CAR_TYPE_CHOICES = [
        ('',        '— Not used for airport transfer —'),
        ('economy', 'Economy'),
        ('midsize', 'Mid-size'),
        ('luxury',  'Luxury'),
        ('van',     'Van / Group'),
    ]

    name            = models.CharField(max_length=100)
    slug            = models.SlugField(unique=True)
    category        = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    badge           = models.CharField(max_length=10, choices=BADGE_CHOICES, default='mid')
    description     = models.CharField(max_length=200, blank=True)
    seats           = models.PositiveSmallIntegerField(default=5)
    fuel            = models.CharField(max_length=20, default='Petrol')
    transmission    = models.CharField(max_length=20, default='Automatic')
    has_ac          = models.BooleanField(default=True)
    has_gps         = models.BooleanField(default=True)
    price_usd       = models.DecimalField(max_digits=8, decimal_places=2, help_text='Daily rate in USD')
    price_kes       = models.DecimalField(max_digits=10, decimal_places=2, help_text='Daily rate in KES')
    price_eur       = models.DecimalField(max_digits=8, decimal_places=2, help_text='Daily rate in EUR')
    driver_fee_usd  = models.DecimalField(max_digits=8, decimal_places=2, default=30, help_text='Extra per day with driver (USD)')
    image           = models.ImageField(upload_to='cars/', blank=True, null=True)
    is_available    = models.BooleanField(default=True)
    order           = models.PositiveSmallIntegerField(default=0)
    transfer_car_type = models.CharField(
        max_length=10, choices=TRANSFER_CAR_TYPE_CHOICES, default='', blank=True,
        help_text='Airport-transfer category. Leave blank to exclude from transfer service.'
    )

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def image_url(self):
        if self.image and self.image.name:
            return self.image.url
        # fallback placeholder
        return '/static/images/cars/placeholder.jpg'

    @property
    def specs_display(self):
        specs = [f'🪑 {self.seats} Seats', f'⛽ {self.fuel}']
        if self.has_ac:
            specs.append('❄️ A/C')
        if self.has_gps:
            specs.append('📡 GPS')
        return specs


# ─────────────────────────────────────────────────────────────
#  BOOKING
# ─────────────────────────────────────────────────────────────
def make_reference():
    from django.utils import timezone
    year = timezone.now().year
    uid  = str(uuid.uuid4()).replace('-', '').upper()[:6]
    return f'DK-{year}-{uid}'


class Booking(models.Model):
    HIRE_TYPE_CHOICES = [
        ('normal',    'Normal Hire'),
        ('long',      'Long-Term Lease'),
        ('corporate', 'Corporate Hire'),
        ('safari',    'Safari Package'),
        ('transfer',  'Airport Transfer'),
    ]
    # Direction of an airport transfer
    TRANSFER_DIRECTION_CHOICES = [
        ('',     '— N/A (not an airport transfer) —'),
        ('FROM', 'JKIA → Destination'),
        ('TO',   'Pickup → JKIA'),
    ]
    # Zone within Nairobi
    TRANSFER_ZONE_CHOICES = [
        ('',          '— N/A —'),
        ('near',      'Near Airport'),
        ('nairobi',   'Nairobi'),
        ('outskirts', 'Outskirts'),
    ]
    # Car type at the moment of booking (locked in price)
    TRANSFER_CAR_TYPE_CHOICES = [
        ('',        '— N/A —'),
        ('economy', 'Economy'),
        ('midsize', 'Mid-size'),
        ('luxury',  'Luxury'),
        ('van',     'Van / Group'),
    ]
    PICKUP_LOCATION_CHOICES = [
        ('JKIA',  'Jomo Kenyatta Airport (NBO)'),
        ('WIL',   'Wilson Airport'),
        ('CBD',   'Nairobi CBD'),
        ('MBA',   'Mombasa Airport (MBA)'),
        ('HOTEL', 'Hotel Delivery'),
        ('other', '📍 Choose Location'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('stripe', 'Card (Stripe)'),
        ('paypal', 'PayPal'),
        ('mpesa',  'M-Pesa'),
    ]
    STATUS_CHOICES = [
        ('pending',   'Pending Payment'),
        ('confirmed', 'Confirmed'),
        ('active',    'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    PAYMENT_STATUS_CHOICES = [
        ('unpaid',   'Unpaid'),
        ('paid',     'Paid'),
        ('refunded', 'Refunded'),
        ('failed',   'Failed'),
    ]

    # Reference
    reference       = models.CharField(max_length=20, unique=True, default=make_reference, editable=False)

    # Customer
    user            = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='bookings')
    first_name      = models.CharField(max_length=60)
    last_name       = models.CharField(max_length=60)
    email           = models.EmailField()
    phone           = models.CharField(max_length=30)
    nationality     = models.CharField(max_length=60, default='Kenya')

    # Vehicle & hire details
    vehicle         = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name='bookings')
    hire_type       = models.CharField(max_length=10, choices=HIRE_TYPE_CHOICES, default='normal')
    with_driver     = models.BooleanField(default=False)
    baby_seat       = models.BooleanField(default=False, help_text='Customer requested a baby/child seat (+$10 flat)')
    pickup_location = models.CharField(max_length=10, choices=PICKUP_LOCATION_CHOICES)
    hotel_address   = models.CharField(max_length=300, blank=True, help_text='Required when Hotel Delivery selected')
    dropoff_location = models.CharField(max_length=300, blank=True)
    pickup_date     = models.DateField()
    pickup_time     = models.TimeField()
    # Return date/time are required for car-rental hires but NOT for airport
    # transfers (which are one-way rides). Hence nullable.
    return_date     = models.DateField(null=True, blank=True)
    return_time     = models.TimeField(null=True, blank=True)

    # ── Airport Transfer fields (only used when hire_type='transfer') ────
    # Direction: 'FROM' = JKIA → destination zone; 'TO' = zone → JKIA
    transfer_direction  = models.CharField(max_length=4, choices=TRANSFER_DIRECTION_CHOICES, default='', blank=True)
    transfer_zone       = models.CharField(max_length=10, choices=TRANSFER_ZONE_CHOICES, default='', blank=True)
    transfer_car_type   = models.CharField(max_length=10, choices=TRANSFER_CAR_TYPE_CHOICES, default='', blank=True)
    transfer_destination = models.CharField(max_length=120, blank=True,
        help_text='Free-text destination/pickup point (e.g. "Sarova Stanley, CBD"). For transfers only.')
    is_night_surcharge  = models.BooleanField(default=False,
        help_text='Pickup is between 22:00 and 06:00 — adds $8 to total.')

    # Pricing (snapshotted at booking time)
    days            = models.PositiveSmallIntegerField(default=1)
    base_price_usd  = models.DecimalField(max_digits=10, decimal_places=2)
    driver_fee_usd  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_usd       = models.DecimalField(max_digits=10, decimal_places=2)
    total_kes       = models.DecimalField(max_digits=12, decimal_places=2)
    total_eur       = models.DecimalField(max_digits=10, decimal_places=2)

    # Payment
    payment_method  = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, blank=True)
    payment_status  = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    payment_reminder_sent = models.BooleanField(default=False, help_text='Customer has been emailed the "complete payment" reminder')
    payment_attempt_at = models.DateTimeField(null=True, blank=True,
                        help_text='Set when the customer initiates a payment (Paystack/PayPal/M-Pesa). Used to suppress reminders for in-progress checkouts.')
    payment_ref     = models.CharField(max_length=200, blank=True)  # Stripe/PayPal/M-Pesa txn id

    # Status
    status          = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')

    # Meta
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    user_agent      = models.TextField(blank=True)
    terms_accepted  = models.BooleanField(default=False,
                        help_text="Customer accepted Terms & Conditions and Cancellation Policy at booking time")
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    notes           = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.reference} – {self.first_name} {self.last_name}'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    def calculate_totals(self):
        """
        Flat per-day pricing — all math done in Decimal for PostgreSQL safety.
            base = vehicle.price_usd × days
            driver fee = vehicle.driver_fee_usd × days (only if with_driver)
            baby seat fee = $10 flat for the whole trip (only if baby_seat)
            total = base + driver fee + baby seat fee
        """
        from decimal import Decimal, ROUND_HALF_UP

        def q(x):
            """Quantize to 2 decimal places — PostgreSQL DecimalField requirement."""
            return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        v = self.vehicle
        days = self.days or 1

        # Convert vehicle prices to Decimal (they already are, but be explicit)
        price_usd  = Decimal(str(v.price_usd))
        driver_fee = Decimal(str(v.driver_fee_usd))
        baby_seat_fee = Decimal('10.00') if self.baby_seat else Decimal('0.00')

        self.base_price_usd = q(price_usd * days)
        self.driver_fee_usd = q(driver_fee * days) if self.with_driver else Decimal('0.00')
        self.total_usd      = q(self.base_price_usd + self.driver_fee_usd + baby_seat_fee)

        # Currency conversions — use Decimal-safe constants
        usd_to_kes = Decimal('130.00')
        usd_to_eur = Decimal('0.92')
        self.total_kes = q(self.total_usd * usd_to_kes)
        self.total_eur = q(self.total_usd * usd_to_eur)

    def pricing_breakdown(self):
        """Human-readable pricing breakdown for emails/receipts."""
        v = self.vehicle
        days = self.days or 1
        return {
            'base_rate':     float(v.price_usd),
            'days':          days,
            'raw_subtotal':  round(float(v.price_usd) * days, 2),
            'modifier_text': self.get_hire_type_display(),
            'after_modifier': float(self.base_price_usd),
            'driver_fee':    float(self.driver_fee_usd),
            'baby_seat':     bool(self.baby_seat),
            'baby_seat_fee': 10.0 if self.baby_seat else 0.0,
            'total':         float(self.total_usd),
            'total_kes':     float(self.total_kes),
        }


# ─────────────────────────────────────────────────────────────
#  PAYMENT LOG
# ─────────────────────────────────────────────────────────────
class PaymentLog(models.Model):
    booking         = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payment_logs')
    method          = models.CharField(max_length=10)
    gateway_ref     = models.CharField(max_length=300, blank=True)
    amount_usd      = models.DecimalField(max_digits=10, decimal_places=2)
    status          = models.CharField(max_length=20)
    raw_response    = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.booking.reference} – {self.method} – {self.status}'


# ─────────────────────────────────────────────────────────────
#  REVIEW
# ─────────────────────────────────────────────────────────────
class Review(models.Model):
    booking         = models.OneToOneField(Booking, null=True, blank=True, on_delete=models.SET_NULL)
    name            = models.CharField(max_length=100)
    location        = models.CharField(max_length=100, blank=True)
    flag_emoji      = models.CharField(max_length=10, default='🇰🇪')
    rating          = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    text            = models.TextField()
    is_published    = models.BooleanField(default=False)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} – {self.rating}★'

    @property
    def stars_display(self):
        return '★' * self.rating + '☆' * (5 - self.rating)


# ─────────────────────────────────────────────────────────────
#  CONTACT / SUPPORT TICKET
# ─────────────────────────────────────────────────────────────
class SupportTicket(models.Model):
    STATUS_CHOICES = [
        ('open',     'Open'),
        ('in_prog',  'In Progress'),
        ('closed',   'Closed'),
    ]
    name        = models.CharField(max_length=100)
    email       = models.EmailField()
    phone       = models.CharField(max_length=30, blank=True)
    subject     = models.CharField(max_length=200)
    message     = models.TextField()
    booking_ref = models.CharField(max_length=20, blank=True)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} – {self.subject[:50]}'


# ─────────────────────────────────────────────────────────────
#  RATE LIMIT LOG (for custom middleware)
# ─────────────────────────────────────────────────────────────
class RateLimitEntry(models.Model):
    ip_address  = models.GenericIPAddressField()
    action      = models.CharField(max_length=30)
    count       = models.PositiveIntegerField(default=1)
    window_start = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('ip_address', 'action')]

    def __str__(self):
        return f'{self.ip_address} – {self.action} – {self.count}'


# ─────────────────────────────────────────────────────────────
#  EMAIL OTP — short-lived single-use code for new account verification
# ─────────────────────────────────────────────────────────────
class EmailOTP(models.Model):
    """
    Stores a 6-digit code emailed to the user during registration.
    One unverified row per email at any time (newer requests replace the older).
    Codes expire after 15 minutes; max 5 wrong attempts then it's invalidated.
    """
    email        = models.EmailField(db_index=True)
    code         = models.CharField(max_length=6)
    user         = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    expires_at   = models.DateTimeField()
    attempts     = models.PositiveSmallIntegerField(default=0)
    verified_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'OTP for {self.email} (verified={self.verified_at is not None})'

    def is_expired(self):
        from django.utils import timezone as tz
        return tz.now() >= self.expires_at

    def is_used(self):
        return self.verified_at is not None