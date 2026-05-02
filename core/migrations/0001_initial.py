from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import django.utils.timezone
import core.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        # ── Vehicle ──────────────────────────────────────────
        migrations.CreateModel(
            name='Vehicle',
            fields=[
                ('id',              models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',            models.CharField(max_length=100)),
                ('slug',            models.SlugField(unique=True)),
                ('category',        models.CharField(choices=[('economy','Economy'),('mid','Mid-Range'),('suv','SUV / 4×4'),('luxury','Luxury'),('van','Van / Minibus'),('safari','Safari Ready')], max_length=20)),
                ('badge',           models.CharField(choices=[('pop','Most Popular'),('eco','Economy'),('lux','Luxury'),('saf','Safari Ready'),('van','Group Travel'),('mid','Mid-Range'),('exec','Executive')], default='mid', max_length=10)),
                ('description',     models.CharField(blank=True, max_length=200)),
                ('seats',           models.PositiveSmallIntegerField(default=5)),
                ('fuel',            models.CharField(default='Petrol', max_length=20)),
                ('transmission',    models.CharField(default='Automatic', max_length=20)),
                ('has_ac',          models.BooleanField(default=True)),
                ('has_gps',         models.BooleanField(default=True)),
                ('price_usd',       models.DecimalField(decimal_places=2, help_text='Daily rate in USD', max_digits=8)),
                ('price_kes',       models.DecimalField(decimal_places=2, help_text='Daily rate in KES', max_digits=10)),
                ('price_eur',       models.DecimalField(decimal_places=2, help_text='Daily rate in EUR', max_digits=8)),
                ('driver_fee_usd',  models.DecimalField(decimal_places=2, default=30, help_text='Extra per day with driver (USD)', max_digits=8)),
                ('image',           models.ImageField(blank=True, null=True, upload_to='cars/')),
                ('is_available',    models.BooleanField(default=True)),
                ('order',           models.PositiveSmallIntegerField(default=0)),
            ],
            options={'ordering': ['order', 'name']},
        ),

        # ── Booking ──────────────────────────────────────────
        migrations.CreateModel(
            name='Booking',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference',        models.CharField(default=core.models.make_reference, editable=False, max_length=20, unique=True)),
                ('first_name',       models.CharField(max_length=60)),
                ('last_name',        models.CharField(max_length=60)),
                ('email',            models.EmailField()),
                ('phone',            models.CharField(max_length=30)),
                ('nationality',      models.CharField(default='Kenya', max_length=60)),
                ('hire_type',        models.CharField(choices=[('self','Self Drive'),('driver','With Driver'),('safari','Safari Package'),('long','Long-Term Hire')], default='self', max_length=10)),
                ('with_driver',      models.BooleanField(default=False)),
                ('pickup_location',  models.CharField(choices=[('JKIA','Jomo Kenyatta Airport (NBO)'),('WIL','Wilson Airport'),('CBD','Nairobi CBD'),('MBA','Mombasa Airport (MBA)'),('HOTEL','Hotel Delivery')], max_length=10)),
                ('hotel_address',    models.CharField(blank=True, help_text='Required when Hotel Delivery selected', max_length=300)),
                ('dropoff_location', models.CharField(blank=True, max_length=300)),
                ('pickup_date',      models.DateField()),
                ('pickup_time',      models.TimeField()),
                ('return_date',      models.DateField()),
                ('return_time',      models.TimeField()),
                ('days',             models.PositiveSmallIntegerField(default=1)),
                ('base_price_usd',   models.DecimalField(decimal_places=2, max_digits=10)),
                ('driver_fee_usd',   models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('total_usd',        models.DecimalField(decimal_places=2, max_digits=10)),
                ('total_kes',        models.DecimalField(decimal_places=2, max_digits=12)),
                ('total_eur',        models.DecimalField(decimal_places=2, max_digits=10)),
                ('payment_method',   models.CharField(blank=True, choices=[('stripe','Card (Stripe)'),('paypal','PayPal'),('mpesa','M-Pesa')], max_length=10)),
                ('payment_status',   models.CharField(choices=[('unpaid','Unpaid'),('paid','Paid'),('refunded','Refunded'),('failed','Failed')], default='unpaid', max_length=10)),
                ('payment_ref',      models.CharField(blank=True, max_length=200)),
                ('status',           models.CharField(choices=[('pending','Pending Payment'),('confirmed','Confirmed'),('active','Active'),('completed','Completed'),('cancelled','Cancelled')], default='pending', max_length=12)),
                ('ip_address',       models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent',       models.TextField(blank=True)),
                ('notes',            models.TextField(blank=True)),
                ('created_at',       models.DateTimeField(auto_now_add=True)),
                ('updated_at',       models.DateTimeField(auto_now=True)),
                ('user',             models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bookings', to='auth.user')),
                ('vehicle',          models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bookings', to='core.vehicle')),
            ],
            options={'ordering': ['-created_at']},
        ),

        # ── PaymentLog ───────────────────────────────────────
        migrations.CreateModel(
            name='PaymentLog',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('method',       models.CharField(max_length=10)),
                ('gateway_ref',  models.CharField(blank=True, max_length=300)),
                ('amount_usd',   models.DecimalField(decimal_places=2, max_digits=10)),
                ('status',       models.CharField(max_length=20)),
                ('raw_response', models.TextField(blank=True)),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('booking',      models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payment_logs', to='core.booking')),
            ],
        ),

        # ── Review ───────────────────────────────────────────
        migrations.CreateModel(
            name='Review',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',         models.CharField(max_length=100)),
                ('location',     models.CharField(blank=True, max_length=100)),
                ('flag_emoji',   models.CharField(default='🇰🇪', max_length=10)),
                ('rating',       models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
                ('text',         models.TextField()),
                ('is_published', models.BooleanField(default=False)),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('booking',      models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.booking')),
            ],
            options={'ordering': ['-created_at']},
        ),

        # ── SupportTicket ────────────────────────────────────
        migrations.CreateModel(
            name='SupportTicket',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',        models.CharField(max_length=100)),
                ('email',       models.EmailField()),
                ('phone',       models.CharField(blank=True, max_length=30)),
                ('subject',     models.CharField(max_length=200)),
                ('message',     models.TextField()),
                ('booking_ref', models.CharField(blank=True, max_length=20)),
                ('status',      models.CharField(choices=[('open','Open'),('in_prog','In Progress'),('closed','Closed')], default='open', max_length=10)),
                ('ip_address',  models.GenericIPAddressField(blank=True, null=True)),
                ('created_at',  models.DateTimeField(auto_now_add=True)),
            ],
        ),

        # ── RateLimitEntry ───────────────────────────────────
        migrations.CreateModel(
            name='RateLimitEntry',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_address',   models.GenericIPAddressField()),
                ('action',       models.CharField(max_length=30)),
                ('count',        models.PositiveIntegerField(default=1)),
                ('window_start', models.DateTimeField(auto_now_add=True)),
            ],
            options={'unique_together': {('ip_address', 'action')}},
        ),
    ]
