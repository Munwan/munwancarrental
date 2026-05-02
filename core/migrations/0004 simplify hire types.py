from django.db import migrations, models


def migrate_old_hire_types(apps, schema_editor):
    """
    Map any existing bookings that used the old hire-type codes to the new
    simplified set:
        self      → normal       (customer then toggles with_driver separately)
        driver    → normal + with_driver = True
        airport   → normal       (airport handled as pickup location now)
    """
    Booking = apps.get_model('core', 'Booking')

    # self → normal
    Booking.objects.filter(hire_type='self').update(hire_type='normal')

    # driver → normal, and force with_driver=True
    Booking.objects.filter(hire_type='driver').update(
        hire_type='normal', with_driver=True
    )

    # airport → normal (airport is now expressed via pickup_location)
    Booking.objects.filter(hire_type='airport').update(hire_type='normal')


def reverse_noop(apps, schema_editor):
    """No sensible reverse — old codes are gone."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_terms_accepted'),
    ]

    operations = [
        # 1. Remap data BEFORE changing the field constraints
        migrations.RunPython(migrate_old_hire_types, reverse_noop),

        # 2. Update field choices + default
        migrations.AlterField(
            model_name='booking',
            name='hire_type',
            field=models.CharField(
                choices=[
                    ('normal',    'Normal Hire'),
                    ('long',      'Long-Term Lease'),
                    ('corporate', 'Corporate Hire'),
                    ('safari',    'Safari Package'),
                ],
                default='normal',
                max_length=10,
            ),
        ),
    ]