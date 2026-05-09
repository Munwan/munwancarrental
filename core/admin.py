from django.contrib import admin, messages
from .models import Vehicle, Booking, PaymentLog, Review, SupportTicket, RateLimitEntry


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