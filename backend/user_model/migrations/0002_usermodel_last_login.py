# Generated by Django 2.1.4 on 2019-10-30 01:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user_model', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='usermodel',
            name='last_login',
            field=models.DateTimeField(blank=True, null=True, verbose_name='last login'),
        ),
    ]
