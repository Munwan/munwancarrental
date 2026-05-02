"""
Munwan Car Rental signals.

When a user logs in, claim any orphan bookings (user=None) that share their
email address. This handles the common case where a customer books as a guest
on Tuesday, then registers/logs in on Wednesday — without this signal their
earlier booking would never appear in their account.
"""
import logging

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

logger = logging.getLogger('drivekenya.signals')


@receiver(user_logged_in)
def claim_orphan_bookings(sender, request, user, **kwargs):
    """
    On every login, attach orphan bookings (user=None) with matching email
    that were created BEFORE this user account existed. The created_at guard
    prevents a guest's later booking from accidentally landing in this account
    if they happen to share an email.
    """
    if not user or not user.email:
        return
    try:
        from datetime import timedelta
        from .models import Booking
        cutoff = user.date_joined + timedelta(hours=1)
        count = Booking.objects.filter(
            user__isnull=True,
            email__iexact=user.email,
            created_at__lte=cutoff,
        ).update(user=user)
        if count:
            logger.info('Login claim: %d orphan bookings → %s', count, user.email)
    except Exception as exc:
        logger.warning('Login claim skipped: %s', exc)