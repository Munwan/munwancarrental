"""
Adds invoice support for corporate hire:
- New payment_status='invoiced' choice (extends existing list)
- invoice_number field — set automatically when corporate booking is submitted
- invoice_issued_at, invoice_due_date timestamps

DB-level: 3 new nullable columns + payment_status choices update (state-only).
Safe to run on production — no data backfill, no data loss.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_booking_parent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='payment_status',
            field=models.CharField(
                choices=[
                    ('unpaid',   'Unpaid'),
                    ('invoiced', 'Invoiced'),
                    ('paid',     'Paid'),
                    ('refunded', 'Refunded'),
                    ('failed',   'Failed'),
                ],
                default='unpaid',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='invoice_number',
            field=models.CharField(
                max_length=20,
                blank=True,
                db_index=True,
                help_text='Invoice number — set automatically for corporate bookings.',
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='invoice_issued_at',
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text='When the invoice was generated and emailed.',
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='invoice_due_date',
            field=models.DateField(
                null=True,
                blank=True,
                help_text='Payment due by this date — defaults to pickup_date minus 1 day.',
            ),
        ),
    ]