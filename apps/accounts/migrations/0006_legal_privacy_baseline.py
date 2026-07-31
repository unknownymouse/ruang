import uuid

import django.db.models.deletion
from django.db import migrations, models

import apps.common.encryption


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_rebrand_site_name")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="privacy_version",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="user",
            name="tos_version",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.CreateModel(
            name="LegalAcceptance",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("subject_id_hash", models.CharField(db_index=True, max_length=64)),
                ("terms_version", models.CharField(max_length=40)),
                ("privacy_version", models.CharField(max_length=40)),
                ("source", models.CharField(default="web", max_length=32)),
                ("source_revision", models.CharField(max_length=64)),
                ("terms_url", models.URLField(max_length=500)),
                ("privacy_url", models.URLField(max_length=500)),
                ("accepted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="legal_acceptances",
                        to="accounts.user",
                    ),
                ),
            ],
            options={"db_table": "accounts_legal_acceptance", "ordering": ("-accepted_at",)},
        ),
        migrations.CreateModel(
            name="PrivacyRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("subject_id_hash", models.CharField(db_index=True, max_length=64)),
                ("requester_email", apps.common.encryption.EncryptedTextField()),
                (
                    "request_type",
                    models.CharField(
                        choices=[
                            ("access", "Access or comprehensive export"),
                            ("correction", "Correction"),
                            ("restriction", "Restriction of processing"),
                            ("objection", "Objection to processing"),
                            ("withdraw_consent", "Withdraw consent"),
                            ("other", "Other privacy request"),
                        ],
                        max_length=32,
                    ),
                ),
                ("details", apps.common.encryption.EncryptedTextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("submitted", "Submitted"),
                            ("in_progress", "In progress"),
                            ("completed", "Completed"),
                            ("rejected", "Rejected"),
                        ],
                        default="submitted",
                        max_length=20,
                    ),
                ),
                ("resolution_notes", apps.common.encryption.EncryptedTextField(blank=True, default="")),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="privacy_requests",
                        to="accounts.user",
                    ),
                ),
            ],
            options={"db_table": "accounts_privacy_request", "ordering": ("-submitted_at",)},
        ),
        migrations.AddConstraint(
            model_name="legalacceptance",
            constraint=models.UniqueConstraint(
                fields=("user", "terms_version", "privacy_version"),
                name="accounts_unique_user_legal_versions",
            ),
        ),
    ]
