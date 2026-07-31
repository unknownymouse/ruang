from django.db import migrations


def rebrand_site_name(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(id=1).update(name="Ruang")


def restore_site_name(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(id=1).update(name="Brightbean")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_set_site_brightbean"),
    ]

    operations = [
        migrations.RunPython(rebrand_site_name, restore_site_name),
    ]
