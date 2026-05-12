"""
Adds parent_booking self-FK to Booking to support the
"extend booking only once" rule.

When a customer extends a booking, the new sibling booking points back at
the original via parent_booking. The original then has .extensions reverse
relation populated — the dashboard checks this to decide whether to show
the Extend button.

This is a metadata + new-column migration. No data backfill needed:
all existing bookings have parent_booking=NULL by default, which is
correct (they're original, not extensions).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_safari_and_remove_long'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='parent_booking',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=models.SET_NULL,
                related_name='extensions',
                to='core.booking',
                help_text='Original booking, if this is an extension.',
            ),
        ),
    ]