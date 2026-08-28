from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_booking_unique_payment_ref_when_paid'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='payment_method',
            field=models.CharField(blank=True, choices=[
                ('paystack', 'Card / Apple Pay (Paystack)'),
                ('mpesa', 'M-Pesa'),
                ('card', 'Card (manual)'),
                ('bank_transfer', 'Bank Transfer'),
            ], max_length=20),
        ),
        migrations.AlterField(
            model_name='paymentlog',
            name='method',
            field=models.CharField(max_length=20),
        ),
    ]
