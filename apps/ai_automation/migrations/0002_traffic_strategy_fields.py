from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_automation", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="brandbrain",
            name="traffic_strategy_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="brandbrain",
            name="traffic_goals",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="brandbrain",
            name="topic_seeds",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="brandbrain",
            name="conversion_actions",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="campaign",
            name="strategy_sources",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
