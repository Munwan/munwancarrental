from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html
from .models import Vehicle, Booking, PaymentLog, Review, SupportTicket, RateLimitEntry


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display  = ['order_with_arrows', 'name', 'category', 'badge', 'price_usd',
                     'price_eur', 'price_kes', 'is_available']
    list_editable = ['is_available']
    list_filter   = ['category', 'is_available']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}
    ordering      = ['order', 'name']
    list_per_page = 50  # all 28 vehicles visible on one page so you can drag in order
    actions       = ['move_to_top', 'move_to_bottom', 'auto_renumber']

    # ── Custom column with up/down/edit-order arrows ─────────────────
    def order_with_arrows(self, obj):
        return format_html(
            '<div style="white-space:nowrap;font-family:monospace;">'
            '<a href="{up}" style="text-decoration:none;font-size:18px;padding:0 4px;" title="Move up">↑</a>'
            '<span style="display:inline-block;min-width:30px;text-align:center;font-weight:bold;">{order}</span>'
            '<a href="{down}" style="text-decoration:none;font-size:18px;padding:0 4px;" title="Move down">↓</a>'
            '</div>',
            up=f'./{obj.pk}/move-up/',
            down=f'./{obj.pk}/move-down/',
            order=obj.order,
        )
    order_with_arrows.short_description = 'Order'
    order_with_arrows.admin_order_field = 'order'

    # ── Custom URLs for ↑ and ↓ buttons ──────────────────────────────
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('<int:pk>/move-up/',   self.admin_site.admin_view(self.move_up_view),   name='vehicle_move_up'),
            path('<int:pk>/move-down/', self.admin_site.admin_view(self.move_down_view), name='vehicle_move_down'),
        ]
        return custom + urls

    def move_up_view(self, request, pk):
        try:
            v = Vehicle.objects.get(pk=pk)
        except Vehicle.DoesNotExist:
            messages.error(request, 'Vehicle not found.')
            return redirect('..')
        # Find the vehicle directly above (lower order, closest)
        prev_v = Vehicle.objects.filter(order__lt=v.order).order_by('-order').first()
        if not prev_v:
            messages.info(request, f'{v.name} is already at the top.')
        else:
            v.order, prev_v.order = prev_v.order, v.order
            v.save(update_fields=['order'])
            prev_v.save(update_fields=['order'])
            messages.success(request, f'Moved {v.name} above {prev_v.name}.')
        return redirect('..')

    def move_down_view(self, request, pk):
        try:
            v = Vehicle.objects.get(pk=pk)
        except Vehicle.DoesNotExist:
            messages.error(request, 'Vehicle not found.')
            return redirect('..')
        next_v = Vehicle.objects.filter(order__gt=v.order).order_by('order').first()
        if not next_v:
            messages.info(request, f'{v.name} is already at the bottom.')
        else:
            v.order, next_v.order = next_v.order, v.order
            v.save(update_fields=['order'])
            next_v.save(update_fields=['order'])
            messages.success(request, f'Moved {v.name} below {next_v.name}.')
        return redirect('..')

    # ── Bulk actions ─────────────────────────────────────────────────
    @admin.action(description='⬆️ Move selected to top of fleet')
    def move_to_top(self, request, queryset):
        # Get the lowest current order, then assign these vehicles to be even lower
        lowest = Vehicle.objects.exclude(pk__in=queryset.values('pk')).order_by('order').first()
        base = (lowest.order if lowest else 0) - len(queryset)
        for i, v in enumerate(queryset.order_by('order', 'name')):
            v.order = base + i
            v.save(update_fields=['order'])
        # Renumber everything cleanly afterwards
        self._renumber()
        self.message_user(request, f'Moved {queryset.count()} vehicle(s) to top.', messages.SUCCESS)

    @admin.action(description='⬇️ Move selected to bottom of fleet')
    def move_to_bottom(self, request, queryset):
        highest = Vehicle.objects.exclude(pk__in=queryset.values('pk')).order_by('-order').first()
        base = (highest.order if highest else 0) + 1
        for i, v in enumerate(queryset.order_by('order', 'name')):
            v.order = base + i
            v.save(update_fields=['order'])
        self._renumber()
        self.message_user(request, f'Moved {queryset.count()} vehicle(s) to bottom.', messages.SUCCESS)

    @admin.action(description='🔢 Renumber 0,1,2... (clean up gaps)')
    def auto_renumber(self, request, queryset):
        self._renumber()
        self.message_user(request, 'Renumbered all vehicles in current order.', messages.SUCCESS)

    @staticmethod
    def _renumber():
        """Reassign order to 0,1,2,... based on current ordering."""
        for i, v in enumerate(Vehicle.objects.order_by('order', 'name')):
            if v.order != i:
                v.order = i
                v.save(update_fields=['order'])


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