from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_hire_type_choices'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='terms_accepted',
            field=models.BooleanField(
                default=False,
                help_text='Customer accepted Terms & Conditions and Cancellation Policy at booking time',
            ),
        ),
    ]