from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004 simplify hire types'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='baby_seat',
            field=models.BooleanField(
                default=False,
                help_text='Customer requested a baby/child seat (+$8 flat)',
            ),
        ),
    ]