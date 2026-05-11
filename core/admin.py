from django.contrib import admin, messages
from .models import (Vehicle, Booking, PaymentLog, Review, SupportTicket,
                     RateLimitEntry, SafariDestination, SafariPricing)


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    """
    Vehicle ordering: just edit the "Order" column directly.
    Lower number = appears earlier on the homepage fleet section.
    Tip: skip numbers (use 10, 20, 30...) to leave room for inserts later.
    """
    list_display       = ['order', 'name', 'category', 'transfer_car_type', 'badge',
                          'price_usd', 'price_eur', 'price_kes', 'is_available']
    list_display_links = ['name']  # required by Django since 'order' is first AND editable
    list_editable      = ['order', 'transfer_car_type', 'is_available']
    list_filter        = ['category', 'transfer_car_type', 'is_available']
    search_fields      = ['name']
    prepopulated_fields = {'slug': ('name',)}
    ordering           = ['order', 'name']
    list_per_page      = 50          # show all 28 vehicles on a single page
    actions            = ['renumber_by_tens', 'renumber_sequential']

    @admin.action(description='🔢 Renumber spaced (10, 20, 30…) — keeps room for inserts')
    def renumber_by_tens(self, request, queryset):
        """
        Renumbers ALL vehicles (not just selected) in current display order
        as 10, 20, 30, 40… so you can later insert a new vehicle "between
        25 and 35" by just typing 30 (won't conflict with existing rows).
        """
        for i, v in enumerate(Vehicle.objects.order_by('order', 'name')):
            new_order = (i + 1) * 10
            if v.order != new_order:
                v.order = new_order
                v.save(update_fields=['order'])
        self.message_user(request, 'Renumbered all vehicles as 10, 20, 30…', messages.SUCCESS)

    @admin.action(description='🔢 Renumber sequential (1, 2, 3…)')
    def renumber_sequential(self, request, queryset):
        """Renumbers ALL vehicles as 1, 2, 3… in current display order."""
        for i, v in enumerate(Vehicle.objects.order_by('order', 'name')):
            new_order = i + 1
            if v.order != new_order:
                v.order = new_order
                v.save(update_fields=['order'])
        self.message_user(request, 'Renumbered all vehicles as 1, 2, 3…', messages.SUCCESS)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display  = ['reference', 'full_name', 'vehicle', 'hire_type', 'pickup_date', 'return_date',
                     'days', 'total_usd', 'payment_method', 'payment_status', 'status', 'created_at']
    list_filter   = ['hire_type', 'status', 'payment_status', 'payment_method', 'pickup_date',
                     'transfer_zone', 'transfer_car_type']
    search_fields = ['reference', 'first_name', 'last_name', 'email', 'phone', 'transfer_destination']
    readonly_fields = ['reference', 'ip_address', 'user_agent', 'created_at', 'updated_at']
    date_hierarchy = 'pickup_date'
    ordering = ['-created_at']
    fieldsets = (
        ('Reference', {'fields': ('reference', 'status', 'payment_status', 'payment_method')}),
        ('Customer', {'fields': ('user', 'first_name', 'last_name', 'email', 'phone', 'nationality')}),
        ('Hire details', {'fields': ('hire_type', 'vehicle', 'with_driver', 'baby_seat',
                                     'pickup_location', 'hotel_address', 'dropoff_location',
                                     'pickup_date', 'pickup_time', 'return_date', 'return_time')}),
        ('Airport Transfer (only when hire_type=transfer)', {
            'classes': ('collapse',),
            'fields': ('transfer_direction', 'transfer_zone', 'transfer_car_type',
                       'transfer_destination', 'is_night_surcharge'),
        }),
        ('Pricing', {'fields': ('days', 'base_price_usd', 'driver_fee_usd', 'total_usd')}),
        ('Meta', {'classes': ('collapse',), 'fields': ('ip_address', 'user_agent', 'created_at', 'updated_at')}),
    )


@admin.register(PaymentLog)
class PaymentLogAdmin(admin.ModelAdmin):
    list_display = ['booking', 'method', 'amount_usd', 'status', 'gateway_ref', 'created_at']
    list_filter  = ['method', 'status']
    search_fields = ['booking__reference', 'gateway_ref']
    readonly_fields = ['created_at']


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display  = ['name', 'rating', 'location', 'is_published', 'created_at']
    list_editable = ['is_published']
    list_filter   = ['is_published', 'rating']
    search_fields = ['name', 'text']


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display  = ['name', 'email', 'subject', 'booking_ref', 'status', 'created_at']
    list_editable = ['status']
    list_filter   = ['status']
    search_fields = ['name', 'email', 'booking_ref', 'subject']
    readonly_fields = ['ip_address', 'created_at']


@admin.register(RateLimitEntry)
class RateLimitEntryAdmin(admin.ModelAdmin):
    list_display = ['ip_address', 'action', 'count', 'window_start']
    list_filter  = ['action']


# ─────────────────────────────────────────────────────────────
#  SAFARI — Destinations and per-vehicle pricing matrix
# ─────────────────────────────────────────────────────────────
class SafariPricingInline(admin.TabularInline):
    """
    Inline pricing rows on the SafariDestination edit page.
    Lets the operator set a price for each safari-ready vehicle at this
    destination without leaving the destination view. The cell for a
    missing (destination, vehicle) combination is treated as "not offered".
    """
    model = SafariPricing
    extra = 0
    fields = ['vehicle', 'price_usd', 'notes']
    autocomplete_fields = ['vehicle']
    verbose_name = 'Vehicle price at this destination'
    verbose_name_plural = 'Vehicle prices at this destination (per day, USD)'


@admin.register(SafariDestination)
class SafariDestinationAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_name', 'distance_km', 'recommended_days',
                    'is_active', 'order', 'price_summary']
    list_editable = ['order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'short_name']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [SafariPricingInline]
    fieldsets = (
        ('Destination', {
            'fields': ('name', 'short_name', 'slug', 'description'),
        }),
        ('Trip planning', {
            'fields': ('distance_km', 'recommended_days'),
        }),
        ('Display', {
            'fields': ('is_active', 'order'),
        }),
    )

    def price_summary(self, obj):
        """Cheapest → most expensive across vehicles at this destination."""
        prices = list(obj.pricing.values_list('price_usd', flat=True))
        if not prices:
            return '—'
        if len(prices) == 1 or min(prices) == max(prices):
            return f'${prices[0]}/day'
        return f'${min(prices)}–${max(prices)}/day'
    price_summary.short_description = 'Price range / day'


@admin.register(SafariPricing)
class SafariPricingAdmin(admin.ModelAdmin):
    """
    Flat list view for power-edit across all (destination × vehicle) cells.
    Useful when adjusting prices across the board (e.g. fuel hike).
    """
    list_display = ['destination', 'vehicle', 'price_usd', 'notes']
    list_filter = ['destination', 'vehicle']
    list_editable = ['price_usd', 'notes']
    autocomplete_fields = ['destination', 'vehicle']
    list_select_related = ['destination', 'vehicle']