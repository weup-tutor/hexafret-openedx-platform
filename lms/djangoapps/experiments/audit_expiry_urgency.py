"""Audit Expiry Urgency experiment (v1) helpers.

Implements enrollment-time assignment via Optimizely and persistence of a stable
`audit_expiry_at` datetime via CourseEnrollmentAttribute.

Design constraints (from ticket):
* Experiment key: audit_expiry_urgency_v1
* Variants: control_5_7_weeks, expiry_7_days
* Assignment unit: user_id
* Stickiness: across sessions/devices and across the configured target courses
* Failure behavior: default to control
"""

import logging
import random
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from django.utils import timezone

from common.djangoapps.course_modes.models import CourseMode
from common.djangoapps.student.models import CourseEnrollmentAttribute
from lms.djangoapps.utils import OptimizelyClient
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from openedx.features.course_duration_limits.access import get_user_course_duration

from .flags import AUDIT_EXPIRY_URGENCY_V1_ENABLED

log = logging.getLogger(__name__)

# Avoid emitting a warning on every enrollment save if the allowlist is missing.
_WARNED_NO_TARGET_COURSES = False


EXPERIMENT_KEY = 'audit_expiry_urgency_v1'

VARIANT_CONTROL = 'control_5_7_weeks'
VARIANT_EXPIRY_7_DAYS = 'expiry_7_days'
VALID_VARIANTS = {VARIANT_CONTROL, VARIANT_EXPIRY_7_DAYS}

ATTRIBUTE_NAMESPACE = 'audit_expiry_experiment'
ATTRIBUTE_NAME_VARIANT = 'variant'
ATTRIBUTE_NAME_AUDIT_EXPIRY_AT = 'audit_expiry_at'

SITE_CONFIG_KEY_TARGET_COURSES = 'AUDIT_EXPIRY_EXPERIMENT_COURSES'

# TEMP: Local testing fallback.
# When set (e.g. in devstack), this forces a specific variant and skips the
# Optimizely lookup entirely.
FORCE_VARIANT_SETTING = 'AUDIT_EXPIRY_FORCE_VARIANT'


def _get_configured_target_course_id_strings():
    """Return configured target course run IDs as a list of strings."""
    default_from_settings = getattr(settings, SITE_CONFIG_KEY_TARGET_COURSES, [])
    site_config_enabled = configuration_helpers.is_site_configuration_enabled()
    configured = configuration_helpers.get_value(SITE_CONFIG_KEY_TARGET_COURSES, default=default_from_settings)

    # Minimal debug logging for rollout validation.
    if log.isEnabledFor(logging.DEBUG):
        if site_config_enabled:
            log.debug('Audit expiry urgency: target courses loaded from SiteConfiguration')
        else:
            log.debug('Audit expiry urgency: target courses loaded from Django settings fallback')

    if configured is None:
        configured = []
    if isinstance(configured, str):
        configured = [configured]
    if not isinstance(configured, list):
        configured = []

    course_ids = [str(item) for item in configured if item]
    if not course_ids:
        global _WARNED_NO_TARGET_COURSES  # pylint: disable=global-statement
        if not _WARNED_NO_TARGET_COURSES:
            log.warning('Audit expiry urgency: no target courses configured (key=%s)', SITE_CONFIG_KEY_TARGET_COURSES)
            _WARNED_NO_TARGET_COURSES = True
    return course_ids


def is_target_course(course_key):
    """Return True if course_key is one of the configured target course runs."""
    return str(course_key) in set(_get_configured_target_course_id_strings())


def _get_attribute(enrollment, name):
    """Get the latest CourseEnrollmentAttribute row for our namespace/name."""
    return enrollment.attributes.filter(namespace=ATTRIBUTE_NAMESPACE, name=name).order_by('id').last()


def get_persisted_variant(enrollment):
    attr = _get_attribute(enrollment, ATTRIBUTE_NAME_VARIANT)
    return attr.value if attr else None


def get_persisted_audit_expiry_at(enrollment):
    attr = _get_attribute(enrollment, ATTRIBUTE_NAME_AUDIT_EXPIRY_AT)
    return attr.value if attr else None


def _set_attribute(enrollment, name, value):
    """Set an enrollment attribute, tolerating duplicates."""
    try:
        CourseEnrollmentAttribute.objects.update_or_create(
            enrollment=enrollment,
            namespace=ATTRIBUTE_NAMESPACE,
            name=name,
            defaults={'value': value},
        )
    except MultipleObjectsReturned:
        # Duplicates are possible (no uniqueness constraint). Prefer updating the latest.
        existing = CourseEnrollmentAttribute.objects.filter(
            enrollment=enrollment,
            namespace=ATTRIBUTE_NAMESPACE,
            name=name,
        ).order_by('id').last()
        if existing:
            existing.value = value
            existing.save()
        else:
            CourseEnrollmentAttribute.objects.create(
                enrollment=enrollment,
                namespace=ATTRIBUTE_NAMESPACE,
                name=name,
                value=value,
            )


def _find_existing_variant_for_user(user, target_course_id_strings):
    """Reuse learner-level assignment by looking for an existing stored variant."""
    if not target_course_id_strings:
        return None

    # Note: do NOT filter on enrollment.is_active; we want reenrollments to retain assignment.
    existing_variant = (
        CourseEnrollmentAttribute.objects.filter(
            enrollment__user=user,
            enrollment__course_id__in=target_course_id_strings,
            namespace=ATTRIBUTE_NAMESPACE,
            name=ATTRIBUTE_NAME_VARIANT,
        )
        .order_by('-id')
        .values_list('value', flat=True)
        .first()
    )

    return existing_variant if existing_variant in VALID_VARIANTS else None


def _forced_variant_from_settings():
    """Return a forced variant if configured for local testing, else None."""
    forced = getattr(settings, FORCE_VARIANT_SETTING, None)
    if forced in VALID_VARIANTS:
        return forced
    if forced is not None:
        log.warning(
            'Audit expiry urgency: invalid %s=%r; ignoring (expected one of %s)',
            FORCE_VARIANT_SETTING,
            forced,
            sorted(VALID_VARIANTS),
        )
    return None


def _activate_optimizely_variant(user):
    """Return variant key from Optimizely activate(), or None on failure."""
    optimizely_client = OptimizelyClient.get_optimizely_client()
    if optimizely_client is None:
        return None
    try:
        log.debug('Audit expiry urgency: calling Optimizely activate (experiment=%s)', EXPERIMENT_KEY)
        variation_key = optimizely_client.activate(EXPERIMENT_KEY, str(user.id))
        log.debug('Audit expiry urgency: Optimizely returned variation=%s (experiment=%s)', variation_key, EXPERIMENT_KEY)
        return variation_key
    except Exception:  # pylint: disable=broad-except
        # Never break enrollment due to Optimizely issues.
        log.exception(
            'Audit expiry urgency: Optimizely activate failed for user_id=%s experiment=%s',
            user.id,
            EXPERIMENT_KEY,
        )
        return None


def choose_variant(user, target_course_id_strings):
    """Choose (or reuse) a learner-level variant."""
    forced_variant = _forced_variant_from_settings()
    if forced_variant:
        log.info('Audit expiry urgency: using forced variant=%s (setting=%s)', forced_variant, FORCE_VARIANT_SETTING)
        return forced_variant

    existing_variant = _find_existing_variant_for_user(user, target_course_id_strings)
    if existing_variant:
        log.debug('Audit expiry urgency: reusing existing variant=%s', existing_variant)
        return existing_variant

    variation_key = _activate_optimizely_variant(user)
    if variation_key in VALID_VARIANTS:
        return variation_key

    # TEMP: Local testing fallback.
    # If we're in DEBUG and Optimizely is unavailable, assign randomly (50/50)
    # to allow local UI validation without Optimizely.
    if settings.DEBUG and OptimizelyClient.get_optimizely_client() is None:
        chosen = random.choice([VARIANT_CONTROL, VARIANT_EXPIRY_7_DAYS])
        log.info('Audit expiry urgency: DEBUG local fallback randomly chose variant=%s', chosen)
        return chosen

    if variation_key is not None:
        log.warning('Audit expiry urgency: unexpected variation=%s; falling back to control', variation_key)
    else:
        log.warning('Audit expiry urgency: Optimizely unavailable; falling back to control')
    return VARIANT_CONTROL


def _content_availability_date(enrollment):
    course_start = getattr(enrollment.course_overview, 'start', None)
    if course_start is None:
        return enrollment.created
    return max(enrollment.created, course_start)


def compute_audit_expiry_at(enrollment, variant, access_duration):
    """Compute the persisted audit expiry datetime for this enrollment."""
    content_availability_date = _content_availability_date(enrollment)
    if variant == VARIANT_EXPIRY_7_DAYS:
        return content_availability_date + timedelta(days=7)
    return content_availability_date + access_duration


def should_process_enrollment(enrollment):
    """Return True if enrollment is eligible for this experiment."""
    if not AUDIT_EXPIRY_URGENCY_V1_ENABLED.is_enabled():
        log.debug('Audit expiry urgency: skipped (waffle disabled)')
        return False
    if not enrollment or not enrollment.user_id:
        log.warning('Audit expiry urgency: skipped (missing enrollment or user)')
        return False
    if not enrollment.is_active:
        log.debug('Audit expiry urgency: skipped (inactive enrollment)')
        return False
    if enrollment.mode != CourseMode.AUDIT:
        log.debug('Audit expiry urgency: skipped (not audit mode)')
        return False
    if not enrollment.course_overview:
        log.warning('Audit expiry urgency: skipped (missing course_overview)')
        return False
    if not is_target_course(enrollment.course_id):
        log.debug('Audit expiry urgency: skipped (course not in allowlist)')
        return False
    # Only apply if Course Duration Limits would normally apply.
    access_duration = get_user_course_duration(enrollment.user, enrollment.course_overview)
    if access_duration is None:
        log.debug('Audit expiry urgency: skipped (CDL not applicable)')
    return access_duration is not None


def maybe_persist_audit_expiry_urgency_attributes(enrollment):
    """Persist variant and audit_expiry_at for an eligible enrollment.

    Safe + idempotent: if audit_expiry_at already exists, this is a no-op.
    """
    if not should_process_enrollment(enrollment):
        return

    # Idempotency: do not overwrite once set.
    if get_persisted_audit_expiry_at(enrollment):
        log.debug('Audit expiry urgency: idempotency skip (audit_expiry_at already persisted)')
        return

    target_course_ids = _get_configured_target_course_id_strings()
    variant = choose_variant(enrollment.user, target_course_ids)

    access_duration = get_user_course_duration(enrollment.user, enrollment.course_overview)
    if access_duration is None:
        # Defensive: should_process_enrollment already checked this.
        return

    audit_expiry_at = compute_audit_expiry_at(enrollment, variant, access_duration)
    if timezone.is_naive(audit_expiry_at):
        audit_expiry_at = timezone.make_aware(audit_expiry_at, timezone=timezone.utc)

    log.debug('Audit expiry urgency: computed audit_expiry_at=%s variant=%s', audit_expiry_at.isoformat(), variant)

    _set_attribute(enrollment, ATTRIBUTE_NAME_VARIANT, variant)
    _set_attribute(enrollment, ATTRIBUTE_NAME_AUDIT_EXPIRY_AT, audit_expiry_at.isoformat())

    log.debug('Audit expiry urgency: persisted attributes for enrollment_id=%s', enrollment.id)
