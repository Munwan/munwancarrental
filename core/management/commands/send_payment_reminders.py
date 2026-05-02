"""
Send "Complete Payment" reminder emails to customers whose bookings are still
unpaid 1+ hour after creation. Run via cron every 5 minutes:

    */5 * * * * cd /app && python manage.py send_payment_reminders

On Appliku, configure this as a Scheduled Task (UI: Application → Scheduled Tasks).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Booking
from core.emails import send_booking_received


class Command(BaseCommand):
    help = "Email 'Complete Payment' reminders to customers with unpaid bookings older than 1 hour."

    def add_arguments(self, parser):
        parser.add_argument(
            '--age-minutes',
            type=int,
            default=60,
            help='Minimum age (minutes) before sending the reminder (default 60).',
        )
        parser.add_argument(
            '--max-age-hours',
            type=int,
            default=24,
            help='Skip bookings older than this — assume the customer has moved on.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be sent without actually sending.',
        )

    def handle(self, *args, **opts):
        age_minutes   = opts['age_minutes']
        max_age_hours = opts['max_age_hours']
        dry_run       = opts['dry_run']
        now = timezone.now()

        # Window: created between (now - max_age_hours) and (now - age_minutes)
        cutoff_old = now - timedelta(minutes=age_minutes)
        cutoff_max = now - timedelta(hours=max_age_hours)

        candidates = Booking.objects.filter(
            payment_status='unpaid',
            payment_reminder_sent=False,
            created_at__lte=cutoff_old,
            created_at__gte=cutoff_max,
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
                    f'(created {booking.created_at})'
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