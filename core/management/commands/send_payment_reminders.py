"""
Sends the "please complete your payment" email to customers whose
bookings have been unpaid for 10 minutes or more.

Called by the cron container every 60 seconds (see docker-compose.yml).

Logic:
  - Loop bookings created >=10 min ago
  - that are payment_status='unpaid' (not 'paid', 'invoiced', 'refunded', 'failed')
  - and payment_reminder_sent=False
  - and the customer hasn't initiated a payment in the last 10 min
  - Send the email exactly once and stamp payment_reminder_sent=True

Corporate bookings (payment_status='invoiced') are skipped — they received
the invoice email already, and the cron filter excludes them naturally.

Empty-handed run (no bookings to remind) returns silently — keeps the
cron log free of noise.
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Booking
from core.emails import send_booking_received


REMINDER_DELAY_MINUTES = 10


class Command(BaseCommand):
    help = "Send the 'complete your payment' email for bookings unpaid 10+ min."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=REMINDER_DELAY_MINUTES)

        # Bookings eligible for the reminder:
        # - created at least 10 min ago
        # - still unpaid (paid/invoiced/refunded/failed are excluded by status filter)
        # - reminder not yet sent
        # - customer hasn't started a checkout in the last 10 min
        #   (payment_attempt_at is stamped when they click Pay; if it's recent,
        #    they're in the middle of paying — don't interrupt with an email)
        qs = Booking.objects.filter(
            created_at__lte=cutoff,
            payment_status='unpaid',
            payment_reminder_sent=False,
        ).exclude(
            payment_attempt_at__gte=cutoff,
        )

        sent_count = 0
        for booking in qs:
            try:
                ok = send_booking_received(booking)
                # Mark sent regardless of email success — we don't want to
                # retry forever and spam. The admin email alert at creation
                # time already gives us visibility.
                Booking.objects.filter(pk=booking.pk).update(
                    payment_reminder_sent=True
                )
                if ok:
                    sent_count += 1
                    self.stdout.write(
                        f'  Sent reminder for {booking.reference} ({booking.email})'
                    )
            except Exception as exc:
                self.stderr.write(
                    f'  Failed for {booking.reference}: {exc}'
                )

        if sent_count:
            self.stdout.write(self.style.SUCCESS(
                f'Sent {sent_count} payment reminder(s).'
            ))