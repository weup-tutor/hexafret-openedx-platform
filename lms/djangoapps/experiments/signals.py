"""Signal handlers for the experiments app."""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from common.djangoapps.student.models import CourseEnrollment

from .audit_expiry_urgency import maybe_persist_audit_expiry_urgency_attributes

log = logging.getLogger(__name__)


@receiver(post_save, sender=CourseEnrollment, dispatch_uid='audit_expiry_urgency_v1_persist_expiry')
def persist_audit_expiry_urgency_attributes(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Persist experiment attributes on enrollment save.

    Notes:
    * Must never block enrollment.
    * Runs on *any* save (not just created=True) because enroll() first creates an
      inactive row and then activates it in a subsequent save.
    """
    if kwargs.get('raw'):
        return

    try:
        # Keep this log at debug level to avoid production noise.
        log.debug(
            'Audit expiry urgency: post_save received for enrollment_id=%s course_id=%s',
            getattr(instance, 'id', None),
            getattr(instance, 'course_id', None),
        )
        maybe_persist_audit_expiry_urgency_attributes(instance)
    except Exception:  # pylint: disable=broad-except
        log.exception(
            'Audit expiry urgency: error while persisting attributes for user_id=%s course_id=%s enrollment_id=%s',
            getattr(instance.user, 'id', None),
            getattr(instance, 'course_id', None),
            getattr(instance, 'id', None),
        )
