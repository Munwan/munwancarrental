from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_payment_attempt_at'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        # Add 'other' choice for pickup_location
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
                    ('other', 'Other (custom address)'),
                ],
                max_length=10,
            ),
        ),
        # New OTP model for email verification at registration
        migrations.CreateModel(
            name='EmailOTP',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(db_index=True, max_length=254)),
                ('code', models.CharField(max_length=6)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(blank=True, null=True,
                                           on_delete=models.deletion.CASCADE,
                                           to='auth.user')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]