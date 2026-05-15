"""
Adds company information fields to Booking, used by Corporate Hire.

When hire_type='corporate', the customer fields (first/last name, email,
phone) represent the company REPRESENTATIVE making the booking. The
company_* fields below identify the COMPANY being billed. Invoices and
confirmation emails address the company by name when these are set.

DB-level: 3 new nullable (blank-default) CharField columns.
Safe to run on production — no data backfill, no data loss.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_invoice'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='company_name',
            field=models.CharField(
                max_length=120,
                blank=True,
                help_text='Company name (corporate hire only).',
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='company_kra_pin',
            field=models.CharField(
                max_length=20,
                blank=True,
                help_text='KRA PIN — required on invoice for tax purposes.',
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='company_address',
            field=models.CharField(
                max_length=300,
                blank=True,
                help_text='Company billing address.',
            ),
        ),
    ]