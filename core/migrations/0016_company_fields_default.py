"""
Fix the company_* fields added by 0015 so they can accept NULL OR default
to empty string. The original migration declared CharField(blank=True)
which Django renders as NOT NULL at the DB level — fine when Django's
ORM is filling the column with '' on save, but a hazard if any code path
constructs a Booking() without setting them (the safari/transfer paths
do exactly this).

This migration:
  1. Backfills existing rows where company_* IS NULL → '' (empty string).
  2. Re-declares the fields with explicit blank=True + default='' so
     subsequent inserts can never be NULL.

DB-level: 1 UPDATE + 3 ALTER COLUMN. Safe + idempotent.
"""
from django.db import migrations, models


def backfill_company_nulls(apps, schema_editor):
    """Set NULL company_* to '' on any existing rows."""
    Booking = apps.get_model('core', 'Booking')
    # Use update() so we hit the DB directly; don't trigger save() (which
    # would fire signals and recompute things we don't want to touch).
    for field in ('company_name', 'company_kra_pin', 'company_address'):
        Booking.objects.filter(**{f'{field}__isnull': True}).update(**{field: ''})


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_company_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_company_nulls, reverse_code=noop_reverse),
        # Re-declare with explicit default so inserts that don't set the
        # column get '' instead of NULL.
        migrations.AlterField(
            model_name='booking',
            name='company_name',
            field=models.CharField(
                max_length=120,
                blank=True,
                default='',
                help_text='Company name (corporate hire only).',
            ),
        ),
        migrations.AlterField(
            model_name='booking',
            name='company_kra_pin',
            field=models.CharField(
                max_length=20,
                blank=True,
                default='',
                help_text='KRA PIN — required on invoice for tax purposes.',
            ),
        ),
        migrations.AlterField(
            model_name='booking',
            name='company_address',
            field=models.CharField(
                max_length=300,
                blank=True,
                default='',
                help_text='Company billing address.',
            ),
        ),
    ]