"""
Updates payment_method choices after PayPal removal.

PayPal closed the business account, so PayPal (and the long-dead Stripe
option) are removed. Remaining methods: Paystack (Card/Apple Pay) + M-Pesa.

choices= changes are validation-only — they don't alter the DB schema.
This migration exists purely to keep Django's migration state in sync so
`makemigrations` doesn't flag a phantom change later.

No data migration: existing rows with payment_method='paypal' (paid
bookings from before PayPal was removed) keep their value. The value is
still readable; it just isn't an offered choice for new bookings.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_company_fields_default'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='payment_method',
            field=models.CharField(
                max_length=10,
                blank=True,
                choices=[
                    ('paystack', 'Card / Apple Pay (Paystack)'),
                    ('mpesa',    'M-Pesa'),
                ],
            ),
        ),
    ]