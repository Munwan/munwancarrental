"""
Send "Complete Payment" reminder emails to customers whose bookings are still
unpaid 10+ minutes after creation/edit, AND who haven't started a checkout
attempt within the last 30 minutes.

Run via cron every 60 seconds (see docker-compose.yml cron service).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core.models import Booking
from core.emails import send_booking_received


class Command(BaseCommand):
    help = "Email 'Complete Payment' reminders to customers with unpaid bookings older than 10 minutes (skipping those with active checkout attempts)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--age-minutes',
            type=int,
            default=10,
            help='Minimum age (minutes) before sending the reminder (default 10).',
        )
        parser.add_argument(
            '--max-age-hours',
            type=int,
            default=24,
            help='Skip bookings older than this — assume the customer has moved on.',
        )
        parser.add_argument(
            '--checkout-grace-minutes',
            type=int,
            default=30,
            help='If the customer initiated payment within this many minutes, skip the reminder.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be sent without actually sending.',
        )

    def handle(self, *args, **opts):
        age_minutes      = opts['age_minutes']
        max_age_hours    = opts['max_age_hours']
        checkout_grace   = opts['checkout_grace_minutes']
        dry_run          = opts['dry_run']
        now = timezone.now()

        # Window: created between (now - max_age_hours) and (now - age_minutes)
        cutoff_old        = now - timedelta(minutes=age_minutes)
        cutoff_max        = now - timedelta(hours=max_age_hours)
        checkout_cutoff   = now - timedelta(minutes=checkout_grace)

        # A booking is reminder-eligible when:
        #   - Still unpaid
        #   - Not already reminded
        #   - Created/edited between max-age and min-age ago
        #   - EITHER never attempted payment, OR last attempt was >30 min ago
        candidates = Booking.objects.filter(
            payment_status='unpaid',
            payment_reminder_sent=False,
            created_at__lte=cutoff_old,
            created_at__gte=cutoff_max,
        ).filter(
            Q(payment_attempt_at__isnull=True) | Q(payment_attempt_at__lte=checkout_cutoff)
        ).order_by('created_at')

        total = candidates.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS('No reminders to send.'))
            return

        sent = 0
        failed = 0

        for booking in candidates:
            if dry_run:
                self.stdout.write(
                    f'[dry-run] would email {booking.email} for {booking.reference} '
                    f'(created {booking.created_at}, attempt={booking.payment_attempt_at})'
                )
                continue

            ok = send_booking_received(booking)
            if ok:
                Booking.objects.filter(pk=booking.pk).update(payment_reminder_sent=True)
                sent += 1
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ Reminder sent to {booking.email} for {booking.reference}')
                )
            else:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Email failed for {booking.reference}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Total candidates: {total}, sent: {sent}, failed: {failed}'
            )
        )