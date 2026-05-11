from django.urls import path
from . import views

urlpatterns = [
    # ── Home ──────────────────────────────────────────────────
    path('',                    views.home,              name='home'),
    path('fleet/',              views.fleet,             name='fleet'),
    path('about/',              views.about,             name='about'),

    # ── Blog (SEO-driven travel guides) ───────────────────────
    path('blog/',                                views.blog_index,    name='blog_index'),
    path('blog/<slug:slug>/',                    views.blog_post,     name='blog_post'),

    # ── SEO: Vehicle detail pages (one URL per car) ───────────
    path('cars/<slug:slug>/',   views.vehicle_detail,    name='vehicle_detail'),

    # ── SEO: Location landing pages ───────────────────────────
    path('car-rental-nairobi/',      views.loc_nairobi, name='location_nairobi'),
    path('car-rental-jkia-airport/', views.loc_jkia,    name='location_jkia'),
    path('car-rental-mombasa/',      views.loc_mombasa, name='location_mombasa'),
    path('car-rental-diani/',        views.loc_diani,   name='location_diani'),

    # ── Static info pages ─────────────────────────────────────
    path('faqs/',               views.faqs,              name='faqs'),
    path('cancellation/',       views.cancellation,      name='cancellation'),
    path('terms/',              views.terms,             name='terms'),
    path('privacy/',            views.privacy,           name='privacy'),

    # ── Booking ───────────────────────────────────────────────
    path('booking/submit/',     views.booking_submit,    name='booking_submit'),
    path('booking/summary/',    views.booking_summary,   name='booking_summary'),
    path('booking/resume/',     views.booking_resume,    name='booking_resume'),
    path('booking/check/',      views.check_booking,     name='check_booking'),

    # ── Safari Package: destinations & live quote ─────────────
    path('safari/destinations/', views.safari_destinations, name='safari_destinations'),
    path('safari/quote/',        views.safari_quote,        name='safari_quote'),

    # ── Payments ──────────────────────────────────────────────
    path('payments/attempt/',            views.payment_attempt,      name='payment_attempt'),
    path('payments/process/',            views.payment_process,      name='payment_process'),
    path('payments/paypal/create/',      views.paypal_create_order,  name='paypal_create_order'),
    path('payments/mpesa/callback/',     views.mpesa_callback,       name='mpesa_callback'),
    path('payments/paystack/webhook/',   views.paystack_webhook,     name='paystack_webhook'),

    # ── Auth ──────────────────────────────────────────────────
    path('auth/login/',         views.auth_login,        name='login'),
    path('auth/logout/',        views.auth_logout,       name='logout'),
    path('auth/register/',      views.auth_register,     name='register'),
    path('auth/verify-email/',  views.verify_email,      name='verify_email'),

    # ── Dashboard ─────────────────────────────────────────────
    path('dashboard/',          views.dashboard,         name='dashboard'),
    path('account/delete/',           views.delete_account,    name='delete_account'),
    path('account/change-password/',  views.change_password,   name='change_password'),

    # ── Support ───────────────────────────────────────────────
    path('support/',            views.support,           name='support'),
]