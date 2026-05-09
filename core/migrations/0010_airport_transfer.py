from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_pickup_choice_rename'),
    ]

    operations = [
        # ── Vehicle.transfer_car_type ──────────────────────
        migrations.AddField(
            model_name='vehicle',
            name='transfer_car_type',
            field=models.CharField(
                blank=True, default='', max_length=10,
                choices=[
                    ('',        '— Not used for airport transfer —'),
                    ('economy', 'Economy'),
                    ('midsize', 'Mid-size'),
                    ('luxury',  'Luxury'),
                    ('van',     'Van / Group'),
                ],
                help_text='Airport-transfer category. Leave blank to exclude from transfer service.',
            ),
        ),
        # ── Booking.hire_type — add 'transfer' choice ──────
        migrations.AlterField(
            model_name='booking',
            name='hire_type',
            field=models.CharField(
                default='normal', max_length=10,
                choices=[
                    ('normal',    'Normal Hire'),
                    ('long',      'Long-Term Lease'),
                    ('corporate', 'Corporate Hire'),
                    ('safari',    'Safari Package'),
                    ('transfer',  'Airport Transfer'),
                ],
            ),
        ),
        # ── Booking.return_date / return_time → nullable ────
        migrations.AlterField(
            model_name='booking',
            name='return_date',
            field=models.DateField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='booking',
            name='return_time',
            field=models.TimeField(null=True, blank=True),
        ),
        # ── Booking airport-transfer fields ─────────────────
        migrations.AddField(
            model_name='booking',
            name='transfer_direction',
            field=models.CharField(
                blank=True, default='', max_length=4,
                choices=[
                    ('',     '— N/A (not an airport transfer) —'),
                    ('FROM', 'JKIA → Destination'),
                    ('TO',   'Pickup → JKIA'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='transfer_zone',
            field=models.CharField(
                blank=True, default='', max_length=10,
                choices=[
                    ('',          '— N/A —'),
                    ('near',      'Near Airport'),
                    ('nairobi',   'Nairobi'),
                    ('outskirts', 'Outskirts'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='transfer_car_type',
            field=models.CharField(
                blank=True, default='', max_length=10,
                choices=[
                    ('',        '— N/A —'),
                    ('economy', 'Economy'),
                    ('midsize', 'Mid-size'),
                    ('luxury',  'Luxury'),
                    ('van',     'Van / Group'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='transfer_destination',
            field=models.CharField(
                blank=True, max_length=120,
                help_text='Free-text destination/pickup point (e.g. "Sarova Stanley, CBD"). For transfers only.',
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='is_night_surcharge',
            field=models.BooleanField(
                default=False,
                help_text='Pickup is between 22:00 and 06:00 — adds $8 to total.',
            ),
        ),
    ]