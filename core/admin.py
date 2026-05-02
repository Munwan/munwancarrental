from django.contrib import admin
from .models import Vehicle, Booking, PaymentLog, Review, SupportTicket, RateLimitEntry


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display  = ['name', 'category', 'badge', 'price_usd', 'price_eur', 'price_kes', 'is_available', 'order']
    list_editable = ['is_available', 'order', 'price_usd']
    list_filter   = ['category', 'is_available']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display  = ['reference', 'full_name', 'vehicle', 'pickup_date', 'return_date',
                     'days', 'total_usd', 'payment_method', 'payment_status', 'status', 'created_at']
    list_filter   = ['status', 'payment_status', 'payment_method', 'pickup_date', 'hire_type']
    search_fields = ['reference', 'first_name', 'last_name', 'email', 'phone']
    readonly_fields = ['reference', 'ip_address', 'user_agent', 'created_at', 'updated_at']
    date_hierarchy = 'pickup_date'
    ordering = ['-created_at']


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
