# Generated by Django 5.1.5 on 2025-02-09 09:49

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_alter_orderstrategy_original_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderstrategy',
            name='table',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='accounts.pricequantitytable'),
        ),
    ]
