"""
Seed Munwan Car Rental's vehicles + reviews to match production database.

Usage:
    docker compose exec web python manage.py seed_data
    docker compose exec web python manage.py seed_data --reset    (DANGEROUS)

Behaviour:
- update_or_create on slug, so safe to re-run; existing vehicles get their
  details refreshed but bookings/orders are preserved.
- Vehicles whose images you've uploaded via /admin/ keep their image — we
  don't touch the image field.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from core.models import Vehicle, Review


# Order matters — earlier rows appear first on the homepage fleet section.
VEHICLES = [
    # ─── Most Popular & Premium SUVs ──────────────────────────────────
    dict(name='Nissan X-Trail',             category='mid',     badge='pop',  seats=5,  fuel='Petrol', price_usd=77.00,  price_kes=10000.00, price_eur=66.00,  driver_fee_usd=25, description='Most popular crossover · Family & city travel'),
    dict(name='Toyota Prado',               category='suv',     badge='lux',  seats=7,  fuel='Diesel', price_usd=108.00, price_kes=14000.00, price_eur=92.00,  driver_fee_usd=30, description='Premium 4×4 · Business & comfort travel'),
    dict(name='Toyota Harrier',             category='suv',     badge='lux',  seats=5,  fuel='Petrol', price_usd=93.00,  price_kes=12000.00, price_eur=79.00,  driver_fee_usd=30, description='Luxury SUV · Comfort cruising'),
    dict(name='Toyota Vanguard',            category='suv',     badge='mid',  seats=5,  fuel='Petrol', price_usd=62.00,  price_kes=8000.00,  price_eur=53.00,  driver_fee_usd=30, description='Reliable SUV · Family travel'),
    dict(name='Toyota Rav4',                category='mid',     badge='mid',  seats=5,  fuel='Petrol', price_usd=77.00,  price_kes=10000.00, price_eur=66.00,  driver_fee_usd=25, description='Compact SUV · Cities & short safaris'),
    dict(name='Subaru Forester',            category='suv',     badge='mid',  seats=5,  fuel='Petrol', price_usd=77.00,  price_kes=10000.00, price_eur=66.00,  driver_fee_usd=30, description='All-Wheel Drive · Rugged & reliable'),
    dict(name='Mazda CX5',                  category='mid',     badge='mid',  seats=5,  fuel='Petrol', price_usd=69.98,  price_kes=9000.00,  price_eur=59.00,  driver_fee_usd=25, description='Crossover SUV · Style & performance'),

    # ─── Safari-Ready 4×4 ────────────────────────────────────────────
    dict(name='Toyota Hilux',               category='safari',  badge='saf',  seats=5,  fuel='Diesel', price_usd=108.00, price_kes=14000.00, price_eur=92.00,  driver_fee_usd=30, description='Safari-ready double-cab · Built for off-road'),
    dict(name='Land Cruiser HardRoof',      category='safari',  badge='saf',  seats=7,  fuel='Diesel', price_usd=217.00, price_kes=28000.00, price_eur=185.00, driver_fee_usd=35, description='Iconic safari 4×4 · Pop-up roof for game viewing'),

    # ─── Luxury & Executive ──────────────────────────────────────────
    dict(name='Toyota Alphard',             category='luxury',  badge='lux',  seats=7,  fuel='Petrol', price_usd=93.00,  price_kes=12000.00, price_eur=79.00,  driver_fee_usd=40, description='Luxury MPV · VIP & executive transfers'),
    dict(name='Toyota Esquire',             category='van',     badge='lux',  seats=7,  fuel='Petrol', price_usd=93.00,  price_kes=12000.00, price_eur=79.00,  driver_fee_usd=35, description='Premium MPV · Business & family'),
    dict(name='Mercedes Benz E Class',      category='luxury',  badge='lux',  seats=5,  fuel='Petrol', price_usd=155.00, price_kes=20000.00, price_eur=132.00, driver_fee_usd=40, description='German luxury · Executive class'),
    dict(name='Mercedes Benz C200',         category='luxury',  badge='lux',  seats=5,  fuel='Petrol', price_usd=155.00, price_kes=20000.00, price_eur=132.00, driver_fee_usd=40, description='Compact luxury · Refined city driving'),
    dict(name='Nissan Patrol',              category='luxury',  badge='lux',  seats=7,  fuel='Petrol', price_usd=155.00, price_kes=20000.00, price_eur=132.00, driver_fee_usd=40, description='Premium 4×4 SUV · Power & prestige'),
    dict(name='Lexus LX570',                category='suv',     badge='lux',  seats=7,  fuel='Petrol', price_usd=363.00, price_kes=55000.00, price_eur=426.00, driver_fee_usd=50, description='Ultra-luxury SUV · Top-tier executive'),
    dict(name='Range Rover E vogue',        category='suv',     badge='lux',  seats=5,  fuel='Petrol', price_usd=387.00, price_kes=50000.00, price_eur=330.00, driver_fee_usd=50, description='Iconic luxury SUV · Statement of arrival'),
    dict(name='Toyota Crown',               category='mid',     badge='exec', seats=5,  fuel='Petrol', price_usd=55.00,  price_kes=7000.00,  price_eur=47.00,  driver_fee_usd=25, description='Executive saloon · Comfortable business travel'),

    # ─── Vans & Group Travel ─────────────────────────────────────────
    dict(name='Toyota Hiace',               category='van',     badge='van',  seats=14, fuel='Diesel', price_usd=132.00, price_kes=17000.00, price_eur=112.00, driver_fee_usd=30, description='14-seat minibus · Tours & group transfers'),
    dict(name='Toyota Coaster Bus',         category='van',     badge='van',  seats=26, fuel='Diesel', price_usd=155.00, price_kes=20000.00, price_eur=132.00, driver_fee_usd=35, description='26-seat coach · Large groups & events'),
    dict(name='Nissan Serena',              category='mid',     badge='mid',  seats=8,  fuel='Petrol', price_usd=77.00,  price_kes=10000.00, price_eur=66.00,  driver_fee_usd=25, description='8-seat MPV · Family & small groups'),

    # ─── Mid-Range Saloons ───────────────────────────────────────────
    dict(name='Mazda Axella',               category='mid',     badge='mid',  seats=5,  fuel='Petrol', price_usd=55.00,  price_kes=7000.00,  price_eur=47.00,  driver_fee_usd=25, description='Stylish saloon · Daily driving'),

    # ─── Economy ─────────────────────────────────────────────────────
    dict(name='Toyota Axio',                category='economy', badge='eco',  seats=5,  fuel='Petrol', price_usd=40.00,  price_kes=5000.00,  price_eur=33.00,  driver_fee_usd=20, description='Reliable economy saloon · Long-distance friendly'),
    dict(name='Toyota Fielder',             category='economy', badge='eco',  seats=5,  fuel='Petrol', price_usd=40.00,  price_kes=5000.00,  price_eur=33.00,  driver_fee_usd=20, description='Estate saloon · City & upcountry trips'),
    dict(name='Toyota Corolla',             category='economy', badge='eco',  seats=5,  fuel='Petrol', price_usd=40.00,  price_kes=5000.00,  price_eur=33.00,  driver_fee_usd=20, description='Classic saloon · Easy city driving'),
    dict(name='Toyota Mark X',              category='economy', badge='eco',  seats=5,  fuel='Petrol', price_usd=40.00,  price_kes=5000.00,  price_eur=32.95,  driver_fee_usd=20, description='Sporty saloon · Comfort & style'),
    dict(name='Toyota Vitz',                category='economy', badge='eco',  seats=5,  fuel='Petrol', price_usd=40.00,  price_kes=5000.00,  price_eur=33.00,  driver_fee_usd=20, description='Compact hatchback · Easy parking, fuel-efficient'),
    dict(name='Nissan Note',                category='economy', badge='eco',  seats=5,  fuel='Petrol', price_usd=40.00,  price_kes=5000.00,  price_eur=33.00,  driver_fee_usd=20, description='Compact hatchback · Budget city runabout'),
    dict(name='Mazda Demio',                category='economy', badge='eco',  seats=5,  fuel='Petrol', price_usd=40.00,  price_kes=5000.00,  price_eur=33.00,  driver_fee_usd=20, description='Subcompact · Fuel-efficient city car'),
]


REVIEWS = [
    dict(name='James H.',       location='United Kingdom · Tourist',    flag='🇬🇧', rating=5, text='Booked the Prado from London before arriving. Car was spotless at JKIA, GPS was perfect for Maasai Mara. Paid in GBP with zero hassle.'),
    dict(name='Wanjiru M.',     location='Nairobi, Kenya · Business',   flag='🇰🇪', rating=5, text='I\'m Kenyan and usually rent from small yards. Munwan Car Rental is next level — clean cars, proper receipts and M-Pesa payment. Finally a local option I trust.'),
    dict(name='Sofia M.',       location='United States · NGO Worker',  flag='🇺🇸', rating=5, text='Rented a Fielder for two weeks on an NGO assignment. Simple USD payment, instant confirmation, super responsive on WhatsApp. Will use again.'),
    dict(name='Brian K.',       location='Mombasa, Kenya · Student',    flag='🇰🇪', rating=4, text='We were a group of 9 students on a field trip. The Hiace van was budget-friendly, clean and the driver knew every back road. Booking took under 5 minutes.'),
    dict(name='Lukas & Family', location='Germany · Family Tourist',    flag='🇩🇪', rating=5, text='Amazing service. The Prado was immaculate for our family safari. Delivered to our hotel. Kids loved the roof hatch. Worth every dollar.'),
    dict(name='Amara O.',       location='Nairobi · Corporate Client',  flag='🇰🇪', rating=5, text='Used the Alphard for an executive airport transfer. Client was very impressed. We now use Munwan Car Rental for all our company car hire needs.'),
]


class Command(BaseCommand):
    help = 'Seed (or refresh) all vehicles and reviews — safe to re-run.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete vehicles and reviews not in this seed list (DANGEROUS).',
        )

    def handle(self, *args, **opts):
        # Vehicles — update_or_create preserves uploaded images & booking history
        # IMPORTANT: only set `order` when CREATING new vehicles. Existing vehicles
        # keep their current order so you can arrange them in the admin and re-run
        # this command without losing your arrangement.
        seeded_slugs = set()
        for i, v in enumerate(VEHICLES):
            slug = slugify(v['name'])
            seeded_slugs.add(slug)
            
            # Defaults that ALWAYS get refreshed (price, description, seats, etc.)
            update_defaults = {**v, 'is_available': True}
            
            # Try to find existing — if it exists, don't touch its order
            try:
                obj = Vehicle.objects.get(slug=slug)
                for key, value in update_defaults.items():
                    setattr(obj, key, value)
                obj.save()
                created = False
            except Vehicle.DoesNotExist:
                # New vehicle — assign it `i` as the seed-list order
                obj = Vehicle.objects.create(slug=slug, order=i, **update_defaults)
                created = True
            
            action = 'Created' if created else 'Updated (order preserved)'
            self.stdout.write(f'  {action}: {obj.name}')

        # Reviews
        seeded_review_names = set()
        for r in REVIEWS:
            seeded_review_names.add(r['name'])
            obj, created = Review.objects.update_or_create(
                name=r['name'],
                defaults={
                    'location':     r['location'],
                    'flag_emoji':   r['flag'],
                    'rating':       r['rating'],
                    'text':         r['text'],
                    'is_published': True,
                },
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(f'  {action} review: {obj.name}')

        # Optional: prune anything not in this seed list
        if opts['reset']:
            extra_vehicles = Vehicle.objects.exclude(slug__in=seeded_slugs)
            extra_reviews  = Review.objects.exclude(name__in=seeded_review_names)
            v_count = extra_vehicles.count()
            r_count = extra_reviews.count()
            if v_count or r_count:
                self.stdout.write(self.style.WARNING(
                    f'\n⚠️  --reset: removing {v_count} extra vehicle(s) and {r_count} extra review(s)'
                ))
                extra_vehicles.delete()
                extra_reviews.delete()

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Seed complete: {len(VEHICLES)} vehicles, {len(REVIEWS)} reviews\n'
            f'   Tip: arrange display order at /admin/core/vehicle/ using ↑/↓ buttons'
        ))