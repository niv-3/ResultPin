from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('store', '0025_expand_available_data_catalogue')]
    operations = [migrations.CreateModel(
        name='SmsOtpLimit',
        fields=[
            ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
            ('window_started_at', models.DateTimeField()),
            ('attempts', models.PositiveIntegerField(default=0)),
        ],
    )]
