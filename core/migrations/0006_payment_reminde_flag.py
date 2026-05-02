from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_baby_seat'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='payment_reminder_sent',
            field=models.BooleanField(
                default=False,
                help_text='Customer has been emailed the "complete payment" reminder',
            ),
        ),
    ]