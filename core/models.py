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

    # ── Safari helpers ───────────────────────────────────────
    def is_safari_ready(self):
        """True if vehicle can be booked under the Safari Package hire type."""
        return self.category == 'safari'

    def safari_price_range(self):
        """
        Returns (min_daily, max_daily) in USD across all active safari
        destinations for this vehicle. Used to show "$X–$Y/day" on the
        frontend fleet card. Returns (price_usd, price_usd) if no safari
        pricing rows exist yet.
        """
        if not self.is_safari_ready():
            return (None, None)
        prices = list(
            self.safari_prices.filter(destination__is_active=True)
                 .values_list('price_usd', flat=True)
        )
        if not prices:
            base = float(self.price_usd)
            return (base, base)
        return (float(min(prices)), float(max(prices)))


# ─────────────────────────────────────────────────────────────
#  SAFARI — Destinations & per-vehicle pricing
# ─────────────────────────────────────────────────────────────
class SafariDestination(models.Model):
    """
    A safari destination (e.g. Maasai Mara, Amboseli) bookable under the
    Safari Package hire type. Customers can pick 1+ destinations for a
    sequential safari trip; pricing per vehicle lives in SafariPricing.
    """
    name              = models.CharField(max_length=80, unique=True,
                                         help_text='e.g. "Maasai Mara National Reserve"')
    short_name        = models.CharField(max_length=40, blank=True,
                                         help_text='Optional shorter label for UI. Defaults to name.')
    slug              = models.SlugField(unique=True, blank=True)
    description       = models.CharField(max_length=300, blank=True,
                                         help_text='1-2 sentence pitch shown on the booking form.')
    distance_km       = models.PositiveSmallIntegerField(
        default=0, help_text='One-way distance from Nairobi in km.')
    recommended_days  = models.PositiveSmallIntegerField(
        default=2, help_text='Recommended minimum days for this destination.')
    is_active         = models.BooleanField(
        default=True, help_text='Uncheck to hide from the booking form without deleting.')
    order             = models.PositiveSmallIntegerField(
        default=0, help_text='Lower = shown first.')

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)[:50]
        if not self.short_name:
            self.short_name = self.name
        super().save(*args, **kwargs)

    @property
    def min_days(self):
        """
        Minimum days for this destination based on driving distance from
        Nairobi. Operationally:
        - ≤100 km  → 1 day  (Nairobi NP, Hell's Gate, Naivasha)
        - ≤200 km  → 2 days (Lake Nakuru, Ol Pejeta)
        - >200 km  → 3 days (Mara, Amboseli, Tsavo, Samburu)
        Driver and vehicle can't economically cover further destinations
        in less time than this. Enforced both client-side (input min)
        and server-side (clamp in quote/submit).
        """
        d = self.distance_km or 0
        if d <= 100:
            return 1
        if d <= 200:
            return 2
        return 3


class SafariPricing(models.Model):
    """
    Per-day price for a (destination × vehicle) combination. This is the
    cell in the pricing matrix. We deliberately store the FULL daily rate
    (vehicle + driver + fuel) here rather than a multiplier — easier for
    admins to reason about and to override case-by-case.
    """
    destination = models.ForeignKey(
        SafariDestination, on_delete=models.CASCADE, related_name='pricing')
    vehicle     = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name='safari_prices',
        limit_choices_to={'category': 'safari'})
    price_usd   = models.DecimalField(
        max_digits=8, decimal_places=2,
        help_text='Daily rate for this vehicle at this destination, USD. Includes vehicle + driver + fuel. Park fees not included.')
    notes       = models.CharField(max_length=200, blank=True,
                                   help_text='Internal admin notes. Not shown to customers.')

    class Meta:
        unique_together = [('destination', 'vehicle')]
        ordering = ['destination__order', 'vehicle__order']
        verbose_name = 'Safari price'
        verbose_name_plural = 'Safari pricing'

    def __str__(self):
        return f'{self.destination.short_name} × {self.vehicle.name} = ${self.price_usd}/day'


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

    # ── Safari Package fields (only used when hire_type='safari') ────
    # Multi-destination sequential trip. Each chosen destination contributes
    # (vehicle_daily_at_that_destination × days_at_that_destination) to total.
    safari_destinations = models.ManyToManyField(
        'SafariDestination', blank=True, related_name='bookings',
        help_text='Safari destinations selected for this trip (sequential).')
    safari_breakdown    = models.JSONField(blank=True, null=True,
        help_text='Snapshot of safari cost breakdown at booking time. '
                  'Shape: [{destination_id, name, days, daily_usd, subtotal_usd}, ...]')

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

    @property
    def daily_rate_usd(self):
        """
        Per-day rate for this booking (vehicle + driver if applicable).
        Used by the extend-booking UI to compute extra-day charges.
        Safari bookings have variable rates per destination so we return
        the average; transfers have no daily concept.
        """
        if self.hire_type == 'transfer':
            return 0
        if self.hire_type == 'safari':
            days = max(int(self.days or 1), 1)
            try:
                return float(self.total_usd or 0) / days
            except Exception:
                return 0
        if not self.vehicle:
            return 0
        rate = float(self.vehicle.price_usd or 0)
        if self.with_driver:
            rate += float(getattr(self.vehicle, 'driver_fee_usd', 0) or 0)
        return rate

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