"""
Airport Transfer pricing & zone detection.

Single source of truth for KES base prices, currency conversion, and the
location → zone mapping. Both Python (views) and JavaScript (booking modal
preview) read from these constants — Python directly, JS via a JSON dump
embedded in the home template.

If you need to change a price or add a zone, edit it here and run:
    python manage.py shell -c "from core.airport_transfer import dump_js_constants; print(dump_js_constants())"
…or just redeploy — home.html embeds the JSON via a template tag.
"""
from decimal import Decimal


# ── Locations grouped by zone ─────────────────────────────────────
# Lowercased, no punctuation. JS does a substring match (location.toLowerCase().includes(item))
# so partial typing also matches ("south b" matches user typing "south b apartments").
ZONE_LOCATIONS = {
    'near': [
        'embakasi', 'fedha', 'south b', 'south c',
        'syokimau', 'mombasa road',
    ],
    'nairobi': [
        'westlands', 'parklands', 'kilimani', 'kileleshwa',
        'hurlingham', 'upperhill', 'nairobi cbd', 'pangani',
        'eastleigh', 'langata', 'ngong road', 'yaya centre',
    ],
    'outskirts': [
        'karen', 'karen hardy', 'runda', 'gigiri',
        'muthaiga', 'lavington', 'spring valley', 'kitisuru',
        'rosslyn', 'ridgeways', 'kiambu road', 'ruaka',
    ],
}

ZONE_LABELS = {
    'near':      'Near Airport',
    'nairobi':   'Nairobi',
    'outskirts': 'Outskirts',
}

# Base prices in KES — keyed by (zone, car_type)
PRICES_KES = {
    ('near',      'economy'):  2500,
    ('near',      'midsize'):  3250,
    ('near',      'luxury'):   4500,
    ('near',      'van'):      5000,
    ('nairobi',   'economy'):  3500,
    ('nairobi',   'midsize'):  4500,
    ('nairobi',   'luxury'):   6500,
    ('nairobi',   'van'):      7000,
    ('outskirts', 'economy'):  5000,
    ('outskirts', 'midsize'):  6500,
    ('outskirts', 'luxury'):   9000,
    ('outskirts', 'van'):     10000,
}

# Night surcharge — flat fee in USD (per spec)
NIGHT_SURCHARGE_USD = Decimal('8.00')
NIGHT_START_HOUR = 22  # 10pm
NIGHT_END_HOUR = 6     # 6am

# Currency conversion (fixed rates for display only — payment processors
# handle real-time conversion on settlement).
KES_PER_USD = Decimal('130')
KES_PER_EUR = Decimal('140')


def detect_zone(location_text: str) -> str:
    """
    Returns 'near' / 'nairobi' / 'outskirts' or '' if no match.
    Case-insensitive substring match against ZONE_LOCATIONS.
    """
    if not location_text:
        return ''
    needle = location_text.strip().lower()
    for zone, locs in ZONE_LOCATIONS.items():
        for loc in locs:
            if loc in needle or needle in loc:
                return zone
    return ''


def is_night_pickup(pickup_time) -> bool:
    """True if pickup time is between 22:00 and 06:00 (inclusive at boundaries)."""
    if not pickup_time:
        return False
    h = pickup_time.hour
    return h >= NIGHT_START_HOUR or h < NIGHT_END_HOUR


def quote(zone: str, car_type: str, pickup_time=None) -> dict:
    """
    Compute price for a transfer.
    Returns: {ok, kes_base, kes_total, usd_total, eur_total, night, error}
    """
    base = PRICES_KES.get((zone, car_type))
    if base is None:
        return {'ok': False, 'error': f'No price for zone={zone!r}, car_type={car_type!r}'}

    night = is_night_pickup(pickup_time)
    night_kes = (NIGHT_SURCHARGE_USD * KES_PER_USD) if night else Decimal('0')
    total_kes = Decimal(base) + night_kes
    total_usd = (total_kes / KES_PER_USD).quantize(Decimal('0.01'))
    total_eur = (total_kes / KES_PER_EUR).quantize(Decimal('0.01'))
    return {
        'ok': True,
        'kes_base':       int(base),
        'kes_night':      int(night_kes),
        'kes_total':      int(total_kes),
        'usd_total':      float(total_usd),
        'eur_total':      float(total_eur),
        'night':          night,
    }


def dump_js_constants() -> str:
    """Returns a JS object literal usable in the home template."""
    import json
    return json.dumps({
        'zone_locations':  ZONE_LOCATIONS,
        'zone_labels':     ZONE_LABELS,
        'prices_kes':      {f'{z}|{c}': p for (z, c), p in PRICES_KES.items()},
        'night_usd':       float(NIGHT_SURCHARGE_USD),
        'night_kes':       float(NIGHT_SURCHARGE_USD * KES_PER_USD),
        'kes_per_usd':     float(KES_PER_USD),
        'kes_per_eur':     float(KES_PER_EUR),
        'night_start':     NIGHT_START_HOUR,
        'night_end':       NIGHT_END_HOUR,
    })