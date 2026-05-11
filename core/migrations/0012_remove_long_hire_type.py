"""
Remove 'Long-Term Lease' hire type.

Business decision: long-term/monthly rentals are now folded into Corporate
Hire (for businesses, NGOs, embassies) or handled as private discounted
quotes on Normal Hire. They are no longer a separate hire type.

This migration:
1. Reassigns any existing bookings with hire_type='long' → 'corporate'
   so existing records remain valid and align with the new positioning.
2. Updates the model field's `choices` list to remove 'long', so the
   admin dropdown and form validation no longer offer it.

DB-level: no schema change (hire_type stays CharField max_length=10).
This is a metadata + data migration only.
"""
from django.db import migrations, models


def reassign_long_bookings(apps, schema_editor):
    """Any historic 'long' booking is reassigned to 'corporate'."""
    Booking = apps.get_model('core', 'Booking')
    n = Booking.objects.filter(hire_type='long').update(hire_type='corporate')
    if n:
        print(f'  Reassigned {n} long-term lease booking(s) to corporate hire.')


def reverse_reassign(apps, schema_editor):
    # No reverse path — we can't know which 'corporate' bookings used to be
    # 'long'. If a rollback is needed, restore from backup. The data merge
    # is one-directional by design.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_safari_destinations'),
    ]

    operations = [
        migrations.RunPython(reassign_long_bookings, reverse_code=reverse_reassign),
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