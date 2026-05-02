from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='hire_type',
            field=models.CharField(
                choices=[
                    ('self',      'Self Drive'),
                    ('driver',    'With Driver'),
                    ('safari',    'Safari Package'),
                    ('long',      'Long-Term Hire'),
                    ('airport',   'Airport Transfer'),
                    ('corporate', 'Corporate Hire'),
                ],
                default='self',
                max_length=10,
            ),
        ),
    ]