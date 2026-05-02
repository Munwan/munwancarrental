"""
Usage:  python manage.py seed_data
Seeds 12 vehicles and 6 reviews.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from core.models import Vehicle, Review


VEHICLES = [
    dict(name='Toyota Prado',    category='suv',     badge='pop',  seats=7, fuel='Diesel',  price_usd=92,  price_kes=11960, price_eur=85,  driver_fee_usd=30, description='Premium 4×4 · Business & comfort travel'),
    dict(name='Nissan X-Trail',  category='suv',     badge='eco',  seats=5, fuel='Petrol',  price_usd=58,  price_kes=7540,  price_eur=53,  driver_fee_usd=25, description='Crossover SUV · Family & city travel'),
    dict(name='Toyota Alphard',  category='luxury',  badge='lux',  seats=7, fuel='Petrol',  price_usd=120, price_kes=15600, price_eur=110, driver_fee_usd=40, description='Luxury MPV · VIP & executive transfers'),
    dict(name='Toyota Noah',     category='van',     badge='van',  seats=8, fuel='Petrol',  price_usd=75,  price_kes=9750,  price_eur=69,  driver_fee_usd=25, description='Family Minivan · Groups & tours'),
    dict(name='Toyota Rav4',     category='suv',     badge='eco',  seats=5, fuel='Petrol',  price_usd=50,  price_kes=6500,  price_eur=46,  driver_fee_usd=25, description='Compact SUV · Cities & short safaris'),
    dict(name='Toyota Esquire',  category='luxury',  badge='exec', seats=7, fuel='Petrol',  price_usd=95,  price_kes=12350, price_eur=87,  driver_fee_usd=35, description='Premium MPV · Business & family'),
    dict(name='Toyota Harrier',  category='suv',     badge='mid',  seats=5, fuel='Petrol',  price_usd=85,  price_kes=11050, price_eur=78,  driver_fee_usd=30, description='Luxury SUV · Comfort cruising'),
    dict(name='Mazda CX5',       category='suv',     badge='mid',  seats=5, fuel='Petrol',  price_usd=68,  price_kes=8840,  price_eur=63,  driver_fee_usd=25, description='Crossover SUV · Style & performance'),
    dict(name='Subaru Forester', category='safari',  badge='saf',  seats=5, fuel='Petrol',  price_usd=62,  price_kes=8060,  price_eur=57,  driver_fee_usd=25, description='All-Wheel Drive · Rugged & reliable'),
    dict(name='Toyota Fielder',  category='economy', badge='eco',  seats=5, fuel='Petrol',  price_usd=38,  price_kes=4940,  price_eur=35,  driver_fee_usd=20, description='Estate Saloon · City & upcountry trips'),
    dict(name='Nissan Note',     category='economy', badge='eco',  seats=5, fuel='Petrol',  price_usd=32,  price_kes=4160,  price_eur=29,  driver_fee_usd=20, description='Compact Hatchback · Budget city runabout'),
    dict(name='Mazda Demio',     category='economy', badge='eco',  seats=5, fuel='Petrol',  price_usd=28,  price_kes=3640,  price_eur=26,  driver_fee_usd=20, description='Subcompact · Fuel-efficient city car'),
]

REVIEWS = [
    dict(name='James H.',       location='United Kingdom · Tourist',    flag='🇬🇧', rating=5, text='Booked the Prado from London before arriving. Car was spotless at JKIA, GPS was perfect for Maasai Mara. Paid in GBP with zero hassle.'),
    dict(name='Wanjiru M.',     location='Nairobi, Kenya · Business',   flag='🇰🇪', rating=5, text='I\'m Kenyan and usually rent from small yards. DriveKenya is next level — clean cars, proper receipts and M-Pesa payment. Finally a local option I trust.'),
    dict(name='Sofia M.',       location='United States · NGO Worker',  flag='🇺🇸', rating=5, text='Rented a Fielder for two weeks on an NGO assignment. Simple USD payment, instant confirmation, super responsive on WhatsApp. Will use again.'),
    dict(name='Brian K.',       location='Mombasa, Kenya · Student',    flag='🇰🇪', rating=4, text='We were a group of 9 students on a field trip. The Noah van was affordable, clean and the driver knew every back road. Booking took under 5 minutes.'),
    dict(name='Lukas & Family', location='Germany · Family Tourist',    flag='🇩🇪', rating=5, text='Amazing service. The Prado was immaculate for our family safari. Delivered to our hotel. Kids loved the roof hatch. Worth every dollar.'),
    dict(name='Amara O.',       location='Nairobi · Corporate Client',  flag='🇰🇪', rating=5, text='Used the Alphard for an executive airport transfer. Client was very impressed. We now use DriveKenya for all our company car hire needs.'),
]


class Command(BaseCommand):
    help = 'Seed initial vehicles and reviews'

    def handle(self, *args, **options):
        # Vehicles
        for i, v in enumerate(VEHICLES):
            obj, created = Vehicle.objects.update_or_create(
                slug=slugify(v['name']),
                defaults={**v, 'slug': slugify(v['name']), 'order': i, 'is_available': True},
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(f'{action}: {obj.name}')

        # Reviews
        for r in REVIEWS:
            obj, created = Review.objects.update_or_create(
                name=r['name'],
                defaults={
                    'location': r['location'], 'flag_emoji': r['flag'],
                    'rating': r['rating'], 'text': r['text'], 'is_published': True,
                },
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(f'{action} review: {obj.name}')

        self.stdout.write(self.style.SUCCESS('✅ Seed complete.'))
