"""
Airport Transfer pricing & zone detection.

Single source of truth for USD base prices, currency conversion, and the
location → zone mapping. Both Python (views) and JavaScript (booking modal
preview) read from these constants — Python directly, JS via a JSON dump
embedded in the home template.

If you need to change a price or add a zone, edit it here and redeploy —
home.html embeds the JSON via a template tag.
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

# ── Base prices in USD — keyed by (zone, car_type) ──────────────
# These are the source of truth. KES & EUR are computed from these
# at quote time. Customer pays the resulting KES total to Paystack.
PRICES_USD = {
    ('near',      'economy'):  19,
    ('near',      'midsize'):  25,
    ('near',      'luxury'):   35,
    ('near',      'van'):      38,
    ('nairobi',   'economy'):  27,
    ('nairobi',   'midsize'):  35,
    ('nairobi',   'luxury'):   50,
    ('nairobi',   'van'):      54,
    ('outskirts', 'economy'):  38,
    ('outskirts', 'midsize'):  50,
    ('outskirts', 'luxury'):   70,
    ('outskirts', 'van'):      77,
}

# Night surcharge — flat fee in USD (10pm–6am pickup)
NIGHT_SURCHARGE_USD = Decimal('8.00')
NIGHT_START_HOUR = 22  # 10pm
NIGHT_END_HOUR = 6     # 6am

# Currency conversion (fixed rates for display only — payment processors
# handle real-time conversion on settlement).
KES_PER_USD = Decimal('130')
EUR_PER_USD = Decimal('0.93')   # ~ EUR 0.93 per USD


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
    Returns: {ok, usd_base, usd_night, usd_total, kes_total, eur_total, night, error}
    """
    base_usd = PRICES_USD.get((zone, car_type))
    if base_usd is None:
        return {'ok': False, 'error': f'No price for zone={zone!r}, car_type={car_type!r}'}

    night = is_night_pickup(pickup_time)
    night_usd = NIGHT_SURCHARGE_USD if night else Decimal('0')
    total_usd = (Decimal(base_usd) + night_usd).quantize(Decimal('0.01'))
    total_kes = (total_usd * KES_PER_USD).quantize(Decimal('1'))   # whole KES
    total_eur = (total_usd * EUR_PER_USD).quantize(Decimal('0.01'))
    return {
        'ok':         True,
        'usd_base':   float(Decimal(base_usd)),
        'usd_night':  float(night_usd),
        'usd_total':  float(total_usd),
        'kes_total':  int(total_kes),
        'eur_total':  float(total_eur),
        'night':      night,
    }


def dump_js_constants() -> str:
    """Returns a JSON string usable in the home template."""
    import json
    return json.dumps({
        'zone_locations':  ZONE_LOCATIONS,
        'zone_labels':     ZONE_LABELS,
        'prices_usd':      {f'{z}|{c}': p for (z, c), p in PRICES_USD.items()},
        'night_usd':       float(NIGHT_SURCHARGE_USD),
        'kes_per_usd':     float(KES_PER_USD),
        'eur_per_usd':     float(EUR_PER_USD),
        'night_start':     NIGHT_START_HOUR,
        'night_end':       NIGHT_END_HOUR,
    })