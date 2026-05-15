import re
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from .models import Booking, SupportTicket, Vehicle


# ─────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────
PHONE_RE = re.compile(r'^\+?[\d\s\-\(\)]{7,20}$')

def clean_text_field(value):
    """Strip HTML tags from text inputs to prevent XSS."""
    import html
    value = html.escape(value.strip())
    return value


# ─────────────────────────────────────────────────────────────
#  Booking Step 1 – Customer & Trip Details
# ─────────────────────────────────────────────────────────────
class BookingStep1Form(forms.Form):
    # ── Bot traps ───────────────────────────────────────────────
    # 1. Honeypot: hidden from humans via CSS; bots fill every field.
    #    If this is non-empty at submit time, we silently reject.
    website          = forms.CharField(required=False, widget=forms.HiddenInput())
    # 2. Time-trap: page sets this to the timestamp when the modal opened.
    #    Real humans take >3 s to fill the form; bots submit in <1 s.
    form_started_at  = forms.CharField(required=False, widget=forms.HiddenInput())

    first_name       = forms.CharField(max_length=60, widget=forms.TextInput(attrs={'placeholder': 'John'}))
    last_name        = forms.CharField(max_length=60, widget=forms.TextInput(attrs={'placeholder': 'Smith'}))
    email            = forms.EmailField(widget=forms.EmailInput(attrs={'placeholder': 'john@example.com'}))
    phone            = forms.CharField(max_length=30, widget=forms.TextInput(attrs={'placeholder': '+254 7XX XXX XXX'}))
    nationality      = forms.ChoiceField(choices=[
        ('Kenya',           'Kenya (Resident)'),
        ('United Kingdom',  'United Kingdom'),
        ('United States',   'United States'),
        ('Germany',         'Germany'),
        ('France',          'France'),
        ('Australia',       'Australia'),
        ('Canada',          'Canada'),
        ('Japan',           'Japan'),
        ('Other',           'Other'),
    ])
    vehicle          = forms.ModelChoiceField(
        queryset=Vehicle.objects.filter(is_available=True),
        empty_label='— Select Vehicle —',
    )
    hire_type        = forms.ChoiceField(choices=Booking.HIRE_TYPE_CHOICES)
    with_driver      = forms.BooleanField(required=False)
    baby_seat        = forms.BooleanField(required=False)
    pickup_location  = forms.ChoiceField(choices=Booking.PICKUP_LOCATION_CHOICES)
    hotel_address    = forms.CharField(max_length=300, required=False,
                                       widget=forms.TextInput(attrs={'placeholder': 'Hotel name & address'}))
    dropoff_location = forms.CharField(max_length=300, required=False,
                                       widget=forms.TextInput(attrs={'placeholder': 'Drop-off address (if different)'}))
    pickup_date      = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    pickup_time      = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    return_date      = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    return_time      = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))

    # Optional account creation
    create_account   = forms.BooleanField(required=False)
    password         = forms.CharField(required=False, min_length=8,
                                       widget=forms.PasswordInput(attrs={'placeholder': 'Min. 8 characters'}))
    password_confirm = forms.CharField(required=False,
                                       widget=forms.PasswordInput(attrs={'placeholder': 'Repeat password'}))

    # REQUIRED: customer must accept T&C and cancellation policy
    terms_accepted   = forms.BooleanField(
        required=True,
        error_messages={'required': 'You must accept the Terms & Conditions and Cancellation Policy to proceed.'}
    )

    def clean_first_name(self):
        return clean_text_field(self.cleaned_data['first_name'])

    def clean_last_name(self):
        return clean_text_field(self.cleaned_data['last_name'])

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError('Enter a valid phone number.')
        return phone

    def clean_hotel_address(self):
        loc = self.cleaned_data.get('pickup_location')
        addr = self.cleaned_data.get('hotel_address', '').strip()
        if loc == 'HOTEL' and not addr:
            raise forms.ValidationError('Please provide the hotel name and address.')
        return clean_text_field(addr) if addr else addr

    def clean(self):
        cleaned = super().clean()

        # ── Bot trap 1: Honeypot ─────────────────────────────────
        # The 'website' field is hidden from humans. Any value = bot.
        if cleaned.get('website'):
            # Silent rejection — act like a generic validation failure
            # so the bot can't learn that it tripped the honeypot.
            raise forms.ValidationError(
                'Invalid submission. Please refresh the page and try again.')

        # ── Bot trap 2: Time-trap ────────────────────────────────
        # The page writes form_started_at (ms since epoch) when the modal
        # opens. A real user takes at least a few seconds to complete the
        # form. Submissions under 3 seconds are almost certainly bots.
        started = cleaned.get('form_started_at')
        if started:
            try:
                import time
                start_ms = int(started)
                now_ms   = int(time.time() * 1000)
                elapsed_s = (now_ms - start_ms) / 1000
                if elapsed_s < 3:
                    raise forms.ValidationError(
                        'Form submitted too quickly. Please take a moment to review and try again.')
                # Also reject unreasonably old forms (>2 hrs open) — likely replay
                if elapsed_s > 7200:
                    raise forms.ValidationError(
                        'This booking form expired. Please refresh and try again.')
            except (ValueError, TypeError):
                # If the timestamp is malformed, treat as suspicious
                raise forms.ValidationError(
                    'Invalid submission. Please refresh the page and try again.')

        pickup_date  = cleaned.get('pickup_date')
        return_date  = cleaned.get('return_date')
        pickup_time  = cleaned.get('pickup_time')
        return_time  = cleaned.get('return_time')

        from django.utils import timezone
        from datetime import timedelta as _td
        today    = timezone.localdate()
        tomorrow = today + _td(days=1)

        if pickup_date and pickup_date < tomorrow:
            # Reject both past dates AND today (same-day bookings aren't allowed
            # operationally — we need at least 1 day to allocate a car and
            # confirm with the customer).
            self.add_error('pickup_date',
                'Pick-up date must be tomorrow or later. Same-day bookings aren\'t available — please WhatsApp us for urgent requests.')

        if pickup_date and return_date:
            if return_date < pickup_date:
                self.add_error('return_date', 'Return date must be after pick-up date.')
            elif return_date == pickup_date:
                # Same-day rental — always too short (minimum is 2 days)
                self.add_error('return_date', 'Minimum rental period is 2 days. Please choose a later return date.')
            else:
                # Different dates — verify gap is at least 2 days
                from datetime import datetime as _dt
                pd = _dt.combine(pickup_date, pickup_time or _dt.min.time())
                rd = _dt.combine(return_date, return_time or _dt.min.time())
                hours = (rd - pd).total_seconds() / 3600
                if hours < 24:  # Less than 1 full day
                    self.add_error('return_date',
                        'Minimum rental period is 2 days. Please choose a later return date.')

                # Corporate Hire requires a 5-day minimum. Enforced here so a
                # JS bypass (DevTools, automation, etc.) still gets blocked.
                hire_type = cleaned.get('hire_type', '') or ''
                if hire_type == 'corporate':
                    day_diff = (return_date - pickup_date).days
                    if day_diff < 5:
                        self.add_error('return_date',
                            'Corporate Hire requires a minimum of 5 days. Please choose a later return date.')

        # Account creation validation
        if cleaned.get('create_account'):
            pwd  = cleaned.get('password', '')
            pwd2 = cleaned.get('password_confirm', '')
            email = (cleaned.get('email') or '').strip()
            if not pwd:
                self.add_error('password', 'Password is required to create an account.')
            elif len(pwd) < 8:
                self.add_error('password', 'Password must be at least 8 characters long.')
            elif pwd != pwd2:
                self.add_error('password_confirm', 'Passwords do not match.')
            elif email:
                # Check for existing account with same email — fail loud, not silent
                from django.contrib.auth.models import User
                if User.objects.filter(email__iexact=email).exists():
                    self.add_error('email',
                        'An account with this email already exists. '
                        'Please sign in first, or untick "Create an account" to continue as a guest.')

        return cleaned


# ─────────────────────────────────────────────────────────────
#  Booking Step 2 – Payment
# ─────────────────────────────────────────────────────────────
class BookingPaymentForm(forms.Form):
    payment_method = forms.ChoiceField(choices=[
        ('paystack', 'Card / Bank / Mobile Money (Paystack)'),
        ('paypal',   'PayPal'),
        ('mpesa',    'M-Pesa (Direct STK Push)'),
    ])
    # Paystack — popup returns a transaction reference after successful payment
    paystack_ref   = forms.CharField(required=False, widget=forms.HiddenInput())
    # PayPal — JS SDK returns order_id
    paypal_order_id = forms.CharField(required=False, widget=forms.HiddenInput())
    # M-Pesa — customer enters Safaricom number for STK push
    mpesa_phone    = forms.CharField(max_length=15, required=False,
                                     widget=forms.TextInput(attrs={'placeholder': '+254 7XX XXX XXX'}))

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('payment_method')
        if method == 'paystack' and not cleaned.get('paystack_ref'):
            self.add_error('paystack_ref', 'Payment reference is required. Please complete the Paystack popup.')
        if method == 'mpesa':
            phone = cleaned.get('mpesa_phone', '').strip()
            if not phone:
                self.add_error('mpesa_phone', 'M-Pesa phone number is required.')
            elif not PHONE_RE.match(phone):
                self.add_error('mpesa_phone', 'Enter a valid M-Pesa phone number.')
        return cleaned


# ─────────────────────────────────────────────────────────────
#  Auth forms
# ─────────────────────────────────────────────────────────────
class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Username or email', 'autofocus': True,
        'autocomplete': 'username',
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Password',
        'autocomplete': 'current-password',
    }))
    # Honeypot: bots fill anything they see; humans don't.
    website = forms.CharField(required=False, widget=forms.HiddenInput())
    # Time-trap: humans take >2s to fill the form. Bots submit immediately.
    form_started_at = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Bot detected.')
        return ''

    def clean(self):
        # Time-trap check before authentication runs
        started = self.cleaned_data.get('form_started_at') if hasattr(self, 'cleaned_data') else None
        if started:
            try:
                import time
                elapsed_ms = (time.time() * 1000) - float(started)
                if elapsed_ms < 1500:  # under 1.5 seconds is bot-fast
                    raise forms.ValidationError('Form submitted too quickly.')
            except (ValueError, TypeError):
                pass
        return super().clean()

    def confirm_login_allowed(self, user):
        """Block disabled accounts and enforce login attempt lockout."""
        super().confirm_login_allowed(user)
        # Lockout check happens at the view level (needs request object)


class RegisterForm(UserCreationForm):
    email      = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        'placeholder': 'you@example.com', 'autocomplete': 'email',
    }))
    first_name = forms.CharField(max_length=60, widget=forms.TextInput(attrs={
        'autocomplete': 'given-name',
    }))
    last_name  = forms.CharField(max_length=60, widget=forms.TextInput(attrs={
        'autocomplete': 'family-name',
    }))
    phone      = forms.CharField(max_length=30, required=False, widget=forms.TextInput(attrs={
        'autocomplete': 'tel',
    }))
    # Honeypot
    website = forms.CharField(required=False, widget=forms.HiddenInput())
    # Time-trap
    form_started_at = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model  = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Force autocomplete=new-password on both password fields to defeat
        # browser password-manager autofill on fresh registrations.
        self.fields['password1'].widget.attrs.update({'autocomplete': 'new-password'})
        self.fields['password2'].widget.attrs.update({'autocomplete': 'new-password'})

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Bot detected.')
        return ''

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            # If the existing account is INACTIVE (started signup but never
            # verified email), allow the new registration — we'll delete the
            # stale one in the view's save() flow. Tells the user politely.
            if not existing.is_active:
                # Don't raise — let the view replace the stale record
                return email
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        # Username must look like an email or a sane handle (no spaces, control chars)
        import re
        if not re.match(r'^[A-Za-z0-9_.@+-]{3,150}$', username):
            raise forms.ValidationError(
                'Username must be 3-150 characters, letters/numbers/._@+- only.'
            )
        return username

    def clean_first_name(self):
        return clean_text_field(self.cleaned_data['first_name'])

    def clean_last_name(self):
        return clean_text_field(self.cleaned_data['last_name'])

    def clean(self):
        # Time-trap
        cleaned = super().clean()
        started = cleaned.get('form_started_at')
        if started:
            try:
                import time
                elapsed_ms = (time.time() * 1000) - float(started)
                if elapsed_ms < 2000:  # under 2 seconds is bot-fast
                    raise forms.ValidationError('Form submitted too quickly. Please try again.')
            except (ValueError, TypeError):
                pass
        return cleaned


# ─────────────────────────────────────────────────────────────
#  Support / Contact
# ─────────────────────────────────────────────────────────────
class SupportForm(forms.ModelForm):
    # Honeypot field (bots fill this, humans don't)
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model  = SupportTicket
        fields = ['name', 'email', 'phone', 'subject', 'message', 'booking_ref']
        widgets = {
            'name':        forms.TextInput(attrs={'placeholder': 'Your full name'}),
            'email':       forms.EmailInput(attrs={'placeholder': 'your@email.com'}),
            'phone':       forms.TextInput(attrs={'placeholder': '+254 7XX XXX XXX'}),
            'subject':     forms.TextInput(attrs={'placeholder': 'How can we help?'}),
            'message':     forms.Textarea(attrs={'rows': 5, 'placeholder': 'Describe your issue...'}),
            'booking_ref': forms.TextInput(attrs={'placeholder': 'DK-2025-XXXXX (optional)'}),
        }

    def clean_website(self):
        # Honeypot: if this is filled, it's a bot
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Bot detected.')
        return ''

    def clean_name(self):
        return clean_text_field(self.cleaned_data['name'])

    def clean_message(self):
        return clean_text_field(self.cleaned_data['message'])


# ─────────────────────────────────────────────────────────────
#  Check booking
# ─────────────────────────────────────────────────────────────
class CheckBookingForm(forms.Form):
    reference = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={'placeholder': 'DK-2025-XXXXXX'}),
    )

    def clean_reference(self):
        ref = self.cleaned_data['reference'].strip().upper()
        import re
        if not re.match(r'^DK-\d{4}-[A-Z0-9]{4,8}$', ref):
            raise forms.ValidationError('Invalid reference format. Example: DK-2025-ABC123')
        return ref