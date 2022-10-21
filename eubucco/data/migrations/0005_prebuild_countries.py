# Generated by Django 3.2.15 on 2022-10-18 12:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0004_unique_names'),
    ]

    operations = [
        migrations.AddField(
            model_name='country',
            name='csv_path',
            field=models.FilePathField(null=True),
        ),
        migrations.AddField(
            model_name='country',
            name='csv_size_in_mb',
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name='country',
            name='gpkg_path',
            field=models.FilePathField(null=True),
        ),
        migrations.AddField(
            model_name='country',
            name='gpkg_size_in_mb',
            field=models.FloatField(null=True),
        ),
    ]
