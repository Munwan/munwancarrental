"""
Adds SafariDestination + SafariPricing models and the M2M / JSON fields
on Booking that track which destinations were chosen and their per-leg costs.

Seed data: 10 standard Kenyan safari destinations with the price ranges
the operator provided, mapped to the 3 existing safari-ready vehicles
(Land Cruiser Hardroof, Toyota Hiace, Toyota Hilux). Prices use the mid
of the provided range so admins can adjust each cell up or down later.
"""
from django.db import migrations, models
import django.db.models.deletion


# Seed prices in USD/day per (destination, vehicle.name).
# Hilux interpolated where competitor data was Hiace-only; Hilux sits
# between Land Cruiser and Hiace in operating cost so we price it ~40%
# below Land Cruiser by default. Operator can tweak each cell.
SEED_DESTINATIONS = [
    # (slug, name, short, distance_km, days, order, description)
    ('maasai-mara',  'Maasai Mara National Reserve', 'Maasai Mara',
     270, 3, 1, "World-famous game reserve — Big Five, Great Migration July-October."),
    ('amboseli',     'Amboseli National Park', 'Amboseli',
     240, 2, 2, "Iconic elephant herds with Kilimanjaro views to the south."),
    ('lake-nakuru',  'Lake Nakuru National Park', 'Lake Nakuru',
     160, 1, 3, "Flamingos, rhinos, leopards. Easy 1-2 day trip from Nairobi."),
    ('lake-naivasha','Lake Naivasha & Hells Gate', 'Lake Naivasha',
     90, 1, 4, "Hippos, boat trips, walking safari at Hell's Gate."),
    ('ol-pejeta',    'Ol Pejeta Conservancy', 'Ol Pejeta',
     220, 2, 5, "The last two northern white rhinos. Big Five, chimpanzee sanctuary."),
    ('tsavo-east',   'Tsavo East National Park', 'Tsavo East',
     320, 2, 6, "Huge red-dust park. Elephants, lions, Yatta Plateau."),
    ('tsavo-west',   'Tsavo West National Park', 'Tsavo West',
     330, 2, 7, "Volcanic landscapes, Mzima Springs, rhino sanctuary."),
    ('samburu',      'Samburu National Reserve', 'Samburu',
     350, 3, 8, "Northern reserve — special-five (Grevy zebra, reticulated giraffe, etc.)."),
    ('nairobi-np',   'Nairobi National Park', 'Nairobi NP',
     10, 1, 9, "Big game inside the city. 5-hour half-day trip."),
    ('hells-gate',   'Hell\'s Gate National Park', "Hell's Gate",
     90, 1, 10, "Cycle and walk among zebra/giraffe. Day trip from Nairobi."),
]

# Per-vehicle daily rate, USD. Land Cruiser uses upper-mid of range,
# Hiace uses upper of range, Hilux estimated.
SEED_PRICING = {
    # destination_slug: {vehicle_name: price_usd}
    'maasai-mara':   {'Land Cruiser HardRoof': 300, 'Toyota Hiace': 195, 'Toyota Hilux': 175},
    'amboseli':      {'Land Cruiser HardRoof': 275, 'Toyota Hiace': 185, 'Toyota Hilux': 165},
    'lake-nakuru':   {'Land Cruiser HardRoof': 265, 'Toyota Hiace': 165, 'Toyota Hilux': 150},
    'lake-naivasha': {'Land Cruiser HardRoof': 250, 'Toyota Hiace': 160, 'Toyota Hilux': 145},
    'ol-pejeta':     {'Land Cruiser HardRoof': 280, 'Toyota Hiace': 175, 'Toyota Hilux': 160},
    'tsavo-east':    {'Land Cruiser HardRoof': 325, 'Toyota Hiace': 215, 'Toyota Hilux': 195},
    'tsavo-west':    {'Land Cruiser HardRoof': 325, 'Toyota Hiace': 215, 'Toyota Hilux': 195},
    'samburu':       {'Land Cruiser HardRoof': 325, 'Toyota Hiace': 210, 'Toyota Hilux': 195},
    'nairobi-np':    {'Land Cruiser HardRoof': 225, 'Toyota Hiace': 135, 'Toyota Hilux': 125},
    'hells-gate':    {'Land Cruiser HardRoof': 265, 'Toyota Hiace': 160, 'Toyota Hilux': 145},
}


def seed_safari_data(apps, schema_editor):
    """Populate destinations + pricing cells based on the seed dicts above."""
    SafariDestination = apps.get_model('core', 'SafariDestination')
    SafariPricing     = apps.get_model('core', 'SafariPricing')
    Vehicle           = apps.get_model('core', 'Vehicle')

    # Create destinations
    dest_objs = {}
    for slug, name, short, dist, days, order, desc in SEED_DESTINATIONS:
        d, _ = SafariDestination.objects.update_or_create(
            slug=slug,
            defaults={
                'name': name, 'short_name': short,
                'distance_km': dist, 'recommended_days': days,
                'order': order, 'description': desc, 'is_active': True,
            },
        )
        dest_objs[slug] = d

    # Create pricing cells for whichever safari vehicles exist
    for slug, prices in SEED_PRICING.items():
        dest = dest_objs[slug]
        for vehicle_name, price in prices.items():
            try:
                v = Vehicle.objects.get(name=vehicle_name, category='safari')
            except Vehicle.DoesNotExist:
                # Vehicle wasn't named exactly that, or hasn't been categorised
                # as safari yet — skip silently. Admin can add the row by hand.
                continue
            SafariPricing.objects.update_or_create(
                destination=dest, vehicle=v,
                defaults={'price_usd': price},
            )


def unseed_safari_data(apps, schema_editor):
    """Reverse migration — wipes all safari destinations & pricing."""
    apps.get_model('core', 'SafariPricing').objects.all().delete()
    apps.get_model('core', 'SafariDestination').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_airport_transfer'),
    ]

    operations = [
        migrations.CreateModel(
            name='SafariDestination',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True,
                    help_text='e.g. "Maasai Mara National Reserve"')),
                ('short_name', models.CharField(max_length=40, blank=True,
                    help_text='Optional shorter label for UI. Defaults to name.')),
                ('slug', models.SlugField(unique=True, blank=True)),
                ('description', models.CharField(max_length=300, blank=True,
                    help_text='1-2 sentence pitch shown on the booking form.')),
                ('distance_km', models.PositiveSmallIntegerField(default=0,
                    help_text='One-way distance from Nairobi in km.')),
                ('recommended_days', models.PositiveSmallIntegerField(default=2,
                    help_text='Recommended minimum days for this destination.')),
                ('is_active', models.BooleanField(default=True,
                    help_text='Uncheck to hide from the booking form without deleting.')),
                ('order', models.PositiveSmallIntegerField(default=0,
                    help_text='Lower = shown first.')),
            ],
            options={'ordering': ['order', 'name']},
        ),
        migrations.CreateModel(
            name='SafariPricing',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price_usd', models.DecimalField(max_digits=8, decimal_places=2,
                    help_text='Daily rate for this vehicle at this destination, USD. Includes vehicle + driver + fuel. Park fees not included.')),
                ('notes', models.CharField(max_length=200, blank=True,
                    help_text='Internal admin notes. Not shown to customers.')),
                ('destination', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='pricing', to='core.safaridestination')),
                ('vehicle', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='safari_prices', to='core.vehicle',
                    limit_choices_to={'category': 'safari'})),
            ],
            options={
                'verbose_name': 'Safari price',
                'verbose_name_plural': 'Safari pricing',
                'ordering': ['destination__order', 'vehicle__order'],
                'unique_together': {('destination', 'vehicle')},
            },
        ),
        migrations.AddField(
            model_name='booking',
            name='safari_destinations',
            field=models.ManyToManyField(blank=True, related_name='bookings',
                to='core.safaridestination',
                help_text='Safari destinations selected for this trip (sequential).'),
        ),
        migrations.AddField(
            model_name='booking',
            name='safari_breakdown',
            field=models.JSONField(blank=True, null=True,
                help_text='Snapshot of safari cost breakdown at booking time. '
                          'Shape: [{destination_id, name, days, daily_usd, subtotal_usd}, ...]'),
        ),
        migrations.RunPython(seed_safari_data, reverse_code=unseed_safari_data),
    ]