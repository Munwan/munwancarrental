from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_payment_reminder_flag'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='payment_attempt_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Set when the customer initiates a payment (Paystack/PayPal/M-Pesa). Used to suppress reminders for in-progress checkouts.',
            ),
        ),
    ]