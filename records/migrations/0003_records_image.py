# Generated by Django 2.2.3 on 2019-07-22 04:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0002_auto_20180402_1755'),
    ]

    operations = [
        migrations.AddField(
            model_name='records',
            name='image',
            field=models.ImageField(blank=True, upload_to='Vote/static/img'),
        ),
    ]
