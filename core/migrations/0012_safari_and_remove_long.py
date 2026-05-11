"""
Production-safe combined migration.

All safari tables already exist in the production DB from a previously
applied (now git-reset) migration. This version:
- Uses SeparateDatabaseAndState for all CREATE TABLE / AddField operations
  (state update only — no SQL touches the DB for those)
- Re-runs seed with update_or_create (idempotent — safe if rows exist)
- Reassigns long→corporate bookings
- Updates hire_type choices
"""
from django.db import migrations, models
import django.db.models.deletion


SEED_DESTINATIONS = [
    ('maasai-mara',  'Maasai Mara National Reserve', 'Maasai Mara',  270, 3, 1, "World-famous game reserve — Big Five, Great Migration July-October."),
    ('amboseli',     'Amboseli National Park',        'Amboseli',     240, 2, 2, "Iconic elephant herds with Kilimanjaro views to the south."),
    ('lake-nakuru',  'Lake Nakuru National Park',     'Lake Nakuru',  160, 1, 3, "Flamingos, rhinos, leopards. Easy 1-2 day trip from Nairobi."),
    ('lake-naivasha','Lake Naivasha & Hells Gate',    'Lake Naivasha', 90, 1, 4, "Hippos, boat trips, walking safari at Hell's Gate."),
    ('ol-pejeta',    'Ol Pejeta Conservancy',         'Ol Pejeta',    220, 2, 5, "The last two northern white rhinos. Big Five, chimpanzee sanctuary."),
    ('tsavo-east',   'Tsavo East National Park',      'Tsavo East',   320, 2, 6, "Huge red-dust park. Elephants, lions, Yatta Plateau."),
    ('tsavo-west',   'Tsavo West National Park',      'Tsavo West',   330, 2, 7, "Volcanic landscapes, Mzima Springs, rhino sanctuary."),
    ('samburu',      'Samburu National Reserve',      'Samburu',      350, 3, 8, "Northern reserve — special-five (Grevy zebra, reticulated giraffe, etc.)."),
    ('nairobi-np',   'Nairobi National Park',         'Nairobi NP',    10, 1, 9, "Big game inside the city. 5-hour half-day trip."),
    ('hells-gate',   "Hell's Gate National Park",     "Hell's Gate",   90, 1, 10, "Cycle and walk among zebra/giraffe. Day trip from Nairobi."),
]

SEED_PRICING = {
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
    SafariDestination = apps.get_model('core', 'SafariDestination')
    SafariPricing     = apps.get_model('core', 'SafariPricing')
    Vehicle           = apps.get_model('core', 'Vehicle')
    for slug, name, short, dist, days, order, desc in SEED_DESTINATIONS:
        d, _ = SafariDestination.objects.update_or_create(
            slug=slug,
            defaults={'name': name, 'short_name': short, 'distance_km': dist,
                      'recommended_days': days, 'order': order,
                      'description': desc, 'is_active': True},
        )
        for vehicle_name, price in SEED_PRICING[slug].items():
            try:
                v = Vehicle.objects.get(name=vehicle_name, category='safari')
                SafariPricing.objects.update_or_create(
                    destination=d, vehicle=v,
                    defaults={'price_usd': price},
                )
            except Vehicle.DoesNotExist:
                pass


def unseed_safari_data(apps, schema_editor):
    apps.get_model('core', 'SafariPricing').objects.all().delete()
    apps.get_model('core', 'SafariDestination').objects.all().delete()


def reassign_long_bookings(apps, schema_editor):
    Booking = apps.get_model('core', 'Booking')
    n = Booking.objects.filter(hire_type='long').update(hire_type='corporate')
    if n:
        print(f'  Reassigned {n} long-term lease booking(s) to corporate hire.')


class Migration(migrations.Migration):

    dependencies = [
        # Depends on the merge migration that IS on the server
        ('core', '0011_merge_0006_payment_reminde_flag_0010_airport_transfer'),
    ]

    operations = [

        # ── All safari tables already exist in production DB ──────────────
        # SeparateDatabaseAndState: update Django's model registry (state)
        # but run ZERO SQL against the database (database_operations=[]).
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='SafariDestination',
                    fields=[
                        ('id', models.AutoField(auto_created=True, primary_key=True,
                            serialize=False, verbose_name='ID')),
                        ('name',             models.CharField(max_length=80, unique=True)),
                        ('short_name',       models.CharField(max_length=40, blank=True)),
                        ('slug',             models.SlugField(unique=True, blank=True)),
                        ('description',      models.CharField(max_length=300, blank=True)),
                        ('distance_km',      models.PositiveSmallIntegerField(default=0)),
                        ('recommended_days', models.PositiveSmallIntegerField(default=2)),
                        ('is_active',        models.BooleanField(default=True)),
                        ('order',            models.PositiveSmallIntegerField(default=0)),
                    ],
                    options={'ordering': ['order', 'name']},
                ),
                migrations.CreateModel(
                    name='SafariPricing',
                    fields=[
                        ('id', models.AutoField(auto_created=True, primary_key=True,
                            serialize=False, verbose_name='ID')),
                        ('price_usd', models.DecimalField(max_digits=8, decimal_places=2)),
                        ('notes',     models.CharField(max_length=200, blank=True)),
                        ('destination', models.ForeignKey(
                            on_delete=django.db.models.deletion.CASCADE,
                            related_name='pricing',
                            to='core.safaridestination')),
                        ('vehicle', models.ForeignKey(
                            on_delete=django.db.models.deletion.CASCADE,
                            related_name='safari_prices',
                            to='core.vehicle',
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
                    field=models.ManyToManyField(
                        blank=True, related_name='bookings',
                        to='core.safaridestination'),
                ),
                migrations.AddField(
                    model_name='booking',
                    name='safari_breakdown',
                    field=models.JSONField(blank=True, null=True),
                ),
            ],
            database_operations=[],  # nothing — all columns/tables already exist
        ),

        # ── Seed data — update_or_create is safe to re-run ───────────────
        migrations.RunPython(seed_safari_data, reverse_code=unseed_safari_data),

        # ── Reassign long→corporate, remove 'long' from choices ──────────
        migrations.RunPython(reassign_long_bookings,
                             reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='booking',
            name='hire_type',
            field=models.CharField(
                choices=[
                    ('normal',    'Normal Hire'),
                    ('corporate', 'Corporate Hire'),
                    ('safari',    'Safari Package'),
                    ('transfer',  'Airport Transfer'),
                ],
                default='normal',
                max_length=10,
            ),
        ),
    ]