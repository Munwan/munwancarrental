from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_email_otp_and_pickup_other'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='pickup_location',
            field=models.CharField(
                choices=[
                    ('JKIA',  'Jomo Kenyatta Airport (NBO)'),
                    ('WIL',   'Wilson Airport'),
                    ('CBD',   'Nairobi CBD'),
                    ('MBA',   'Mombasa Airport (MBA)'),
                    ('HOTEL', 'Hotel Delivery'),
                    ('other', '📍 Choose Location'),
                ],
                max_length=10,
            ),
        ),
    ]