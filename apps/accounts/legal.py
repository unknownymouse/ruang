import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LegalAcceptance


def subject_id_hash(user):
    """Stable pseudonymous identifier for legal records after deletion."""
    return hmac.new(
        settings.RUANG_PRIVACY_AUDIT_KEY.encode("utf-8"),
        str(user.pk).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@transaction.atomic
def record_current_legal_acceptance(user, *, source, accepted_at=None):
    """Update the user and retain versioned, data-minimized acceptance evidence."""
    accepted_at = accepted_at or timezone.now()
    user.tos_accepted_at = accepted_at
    user.tos_version = settings.RUANG_TERMS_VERSION
    user.privacy_version = settings.RUANG_PRIVACY_VERSION
    user.save(update_fields=["tos_accepted_at", "tos_version", "privacy_version"])
    acceptance, _ = LegalAcceptance.objects.get_or_create(
        user=user,
        terms_version=settings.RUANG_TERMS_VERSION,
        privacy_version=settings.RUANG_PRIVACY_VERSION,
        defaults={
            "subject_id_hash": subject_id_hash(user),
            "source": source,
            "source_revision": settings.RUANG_SOURCE_CODE_REVISION,
            "terms_url": settings.RUANG_TERMS_URL,
            "privacy_url": settings.RUANG_PRIVACY_URL,
        },
    )
    return acceptance
