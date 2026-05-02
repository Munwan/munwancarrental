"""
DriveKenya sitemaps for SEO.
Serves /sitemap.xml with all static pages + dynamic vehicle detail pages +
location pages. Submit this URL in Google Search Console.
"""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Vehicle


class StaticViewSitemap(Sitemap):
    """Static pages with stable URLs."""
    priority = 0.9
    changefreq = 'weekly'
    protocol = 'https'

    def items(self):
        return [
            'home', 'fleet', 'faqs', 'cancellation', 'terms', 'support',
            'about', 'check_booking',
            'location_nairobi', 'location_jkia',
            'location_mombasa', 'location_diani',
        ]

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        # Homepage gets highest priority
        return {
            'home': 1.0,
            'fleet': 0.9,
            'location_nairobi': 0.9,
            'location_jkia': 0.9,
            'faqs': 0.8,
            'about': 0.7,
            'support': 0.6,
            'cancellation': 0.5,
            'check_booking': 0.4,
        }.get(item, 0.7)


class VehicleSitemap(Sitemap):
    """One URL per vehicle — huge long-tail SEO win."""
    priority = 0.8
    changefreq = 'monthly'
    protocol = 'https'

    def items(self):
        return Vehicle.objects.filter(is_available=True)

    def location(self, obj):
        return reverse('vehicle_detail', kwargs={'slug': obj.slug})

    def lastmod(self, obj):
        return getattr(obj, 'updated_at', None)


sitemaps = {
    'static':   StaticViewSitemap,
    'vehicles': VehicleSitemap,
}