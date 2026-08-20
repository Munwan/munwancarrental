'use strict';

// ── Globals ──────────────────────────────────────────────
let currentStep    = 1;
let pendingBooking = null;
let accOpen        = false;
let currentPayTab  = 'paystack';
let currentFwSub   = 'card';
let VEHICLES       = [];
let TRANSFER_CONSTS = {};   // populated from #transferConstants script tag

// ── Boot ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  try {
    const el = document.getElementById('vehicleData');
    if (el) VEHICLES = JSON.parse(el.textContent || '[]');
  } catch (e) { VEHICLES = []; }
  try {
    const tc = document.getElementById('transferConstants');
    if (tc) TRANSFER_CONSTS = JSON.parse(tc.textContent || '{}');
  } catch (e) { TRANSFER_CONSTS = {}; }

  // ── Email links: on mobile, swap Gmail-web URLs for mailto: so the
  //    native Gmail / Outlook / Mail app opens instead of the browser.
  try {
    const isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
    if (isMobile) {
      document.querySelectorAll('a[href*="mail.google.com/mail"]').forEach(a => {
        const url = new URL(a.href);
        const to = url.searchParams.get('to');
        if (to) {
          a.href = 'mailto:' + to;
          a.removeAttribute('target');  // open in mail app, not new tab
        }
      });
    }
  } catch (_) {}

  const today = new Date().toISOString().split('T')[0];
  ['qs_pickup_date','qs_return_date'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.min = today; if (!el.value) el.value = today; }
  });
  const qsRet = document.getElementById('qs_return_date');
  if (qsRet && !qsRet.value) {
    const t = new Date(); t.setDate(t.getDate() + 1);
    qsRet.value = t.toISOString().split('T')[0];
  }

  // hire-type tabs (top of homepage) open booking modal & sync to modal pills
  document.querySelectorAll('#hireTabs .tab').forEach(tab => {
    tab.addEventListener('click', () => {
      // Safari now lives on its own indexable page — send it there instead
      // of opening the modal. All other hire types are unchanged below.
      if (tab.dataset.type === 'safari') { window.location.href = '/safari/'; return; }
      document.querySelectorAll('#hireTabs .tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      openBookingModal();
      const type = tab.dataset.type || 'normal';
      if (typeof setHireType === 'function') setHireType(type);
    });
  });

  ['b_pickup_date','b_return_date','b_with_driver','b_driver_option'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', updatePricingPreview);
  });
  // b_hire_type is now driven by setHireType() — see below.

  const qsPick = document.getElementById('qs_pickup');
  if (qsPick) qsPick.addEventListener('change', () => {
    const wrap = document.getElementById('hotelAddrWrap');
    if (wrap) wrap.style.display = qsPick.value === 'HOTEL' ? '' : 'none';
  });

  const bOverlay = document.getElementById('bookingOverlay');
  if (bOverlay) bOverlay.addEventListener('click', e => { if (e.target === bOverlay) closeBookingModal(); });
  const cOverlay = document.getElementById('checkOverlay');
  if (cOverlay) cOverlay.addEventListener('click', e => { if (e.target === cOverlay) closeCheckModal(); });
  const refInput = document.getElementById('checkRefInput');
  if (refInput) refInput.addEventListener('keydown', e => { if (e.key === 'Enter') doCheckBooking(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeBookingModal(); closeCheckModal(); } });
  document.addEventListener('click', e => {
    const menu = document.getElementById('mobileMenu');
    const burger = document.querySelector('.nav-burger');
    if (menu && burger && !menu.contains(e.target) && !burger.contains(e.target))
      menu.classList.remove('open');
  });

  // ── Resume unpaid booking from email link ─────────────
  // If the customer clicks "Complete Payment" in their email, we land here
  // with ?resume=DK-2026-XXXXXX. Two outcomes:
  //   • Booking still unpaid → fetch summary, jump to Step 2 (payment).
  //   • Booking already paid → redirect to /check-booking/?reference=...
  //     so the customer sees their PAID receipt instead of being asked
  //     to pay again. (Common scenario: customer pays, then finds the
  //     stale email and clicks the button.)
  try {
    const params = new URLSearchParams(window.location.search);
    const resumeRef = params.get('resume');
    if (resumeRef) {
      // Check if this resume was from an extension flow. If so, we trap
      // Back navigation — extensions create a pending booking the moment
      // the customer clicks Continue, so going Back leaves an orphan
      // unpaid record in the database AND a stale modal state. Easier
      // to keep them on the payment page until they pay or cancel.
      let isExtensionFlow = false;
      try {
        const ext = sessionStorage.getItem('munwan_pending_extension');
        if (ext) {
          const parsed = JSON.parse(ext);
          if (parsed && parsed.extensionRef === resumeRef) {
            isExtensionFlow = true;
          }
        }
      } catch (_) {}

      fetch('/booking/summary/?reference=' + encodeURIComponent(resumeRef),
            { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(r => r.json())
        .then(data => {
          if (data.ok) {
            pendingBooking = {
              reference:   data.reference,
              vehicle:     data.vehicle,
              days:        data.days,
              total_usd:   data.total_usd,
              total_kes:   data.total_kes,
              total_eur:   data.total_eur,
              with_driver: data.with_driver,
              base_price:  data.base_price || data.total_usd,
              driver_fee:  data.driver_fee || '0',
              is_transfer: !!data.is_transfer,
            };
            populateOrderSummary(pendingBooking);
            openBookingModal();
            currentStep = 2;
            updateStepUI();

            // ── BACK-BUTTON TRAP for extension flow ────────────────
            // Push a sentinel state. If the user clicks Back, popstate
            // fires immediately (because we pushed). We re-push so they
            // stay on the page. This is the standard "trap" pattern.
            // The "X Close" button in the modal still works — it doesn't
            // use history navigation.
            if (isExtensionFlow) {
              try {
                history.pushState({ extTrap: true }, '', window.location.href);
                window.addEventListener('popstate', function _extPop(ev) {
                  // Re-push so back navigation stays here. We also show a
                  // brief inline message so the user understands what's
                  // happening rather than feeling like back is broken.
                  history.pushState({ extTrap: true }, '', window.location.href);
                  // Show a polite notice (idempotent — only adds one)
                  if (!document.getElementById('extTrapNotice')) {
                    const note = document.createElement('div');
                    note.id = 'extTrapNotice';
                    note.textContent = 'Please complete the extension payment or close this window.';
                    note.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);' +
                      'background:#1F2937;color:#fff;padding:10px 18px;border-radius:8px;' +
                      'font-family:Poppins,sans-serif;font-size:.85rem;font-weight:600;' +
                      'box-shadow:0 8px 24px rgba(0,0,0,.3);z-index:9999;transition:opacity .3s';
                    document.body.appendChild(note);
                    setTimeout(function(){
                      note.style.opacity = '0';
                      setTimeout(function(){ if (note.parentNode) note.parentNode.removeChild(note); }, 400);
                    }, 2400);
                  }
                });
              } catch (_) {}
            }
          } else if (data.already_paid) {
            // Already paid — redirect to /booking/check/ with reference so the
            // customer sees the PAID status instead of being asked to pay again.
            // Also clean up the extension flag so a future Back works normally.
            try { sessionStorage.removeItem('munwan_pending_extension'); } catch (_) {}
            window.location.replace('/booking/check/?reference=' + encodeURIComponent(data.reference));
          }
        })
        .catch(() => {});
    }

    // ── Back from payment: restore booking + form fields ─────────
    // After submitStep1 succeeds we persist the inputs + booking response
    // in sessionStorage. If the user clicks browser Back from the payment
    // page (and there's no ?resume= since the home URL was clean), we
    // detect that sessionStorage flag and:
    //  1. Reopen the modal at Step 1
    //  2. Pre-fill every form field from the persisted inputs
    //  3. Set pendingBooking → next submit goes through edit_ref so the
    // NOTE: We used to restore a booking from sessionStorage here on
    // page load (for browser-Back from the payment page). That was
    // unreliable — it depended on the customer landing back on "/" with
    // a clean reload, which doesn't always happen. It's been replaced by
    // an in-page back-button trap installed when the payment step opens
    // (see _installPaymentBackTrap in updateStepUI). The trap keeps the
    // customer on the payment step instead of letting Back navigate away
    // to a state we then have to reconstruct.

    // ── ?book=1 from external pages (e.g. blog Book Now button) ──
    if (params.get('book') === '1') {
      // Defer slightly so the page has finished rendering & scrolled
      setTimeout(() => {
        if (typeof openBookingModal === 'function') openBookingModal();
        // Pre-select vehicle if ?car= was passed (from vehicle detail page)
        const carId = params.get('car');
        if (carId) {
          const sel = document.getElementById('b_vehicle');
          if (sel) { sel.value = String(carId); }
        }
        // Pre-select hire type if ?type= was passed (from footer service links)
        const hireType = params.get('type');
        if (hireType) {
          const tsel = document.getElementById('b_hire_type');
          if (tsel) { tsel.value = String(hireType); }
        }
        if (typeof updatePricingPreview === 'function') updatePricingPreview();
        // Clean URL so refresh doesn't re-trigger
        window.history.replaceState({}, '', window.location.pathname + window.location.hash);
      }, 250);
    }
  } catch (_) {}
});

// ── CSRF ─────────────────────────────────────────────────
function getCsrf() {
  const el = document.getElementById('csrfToken');
  if (el && el.value) return el.value;
  const m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}

// ── Fetch helper ──────────────────────────────────────────
async function postJSON(url, data) {
  const csrf = getCsrf();
  const body = new URLSearchParams(data);
  body.append('csrfmiddlewaretoken', csrf);
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrf,
      },
      body: body,
    });
  } catch (e) {
    // fetch throws for genuine network failures only — DNS, refused, offline.
    // Make this distinguishable from HTTP errors so the UI can show different
    // wording (humanisePaymentError keys on the word "network").
    throw new Error('Network error — please check your connection and try again.');
  }
  let json;
  try { json = await response.json(); }
  catch (_) {
    // Server returned non-JSON. status is meaningful here; pass it on so
    // humanisePaymentError can translate.
    throw new Error('Server error (' + response.status + ') — please try again.');
  }
  return json;
}

// ── DOM helpers ───────────────────────────────────────────
function $id(id) { return document.getElementById(id); }
function val(id) { const e=$id(id); if(!e) return ''; return e.type==='checkbox' ? e.checked : e.value; }
function setText(id, t) { const e=$id(id); if(e) e.textContent=String(t); }
function setHTML(id, h) { const e=$id(id); if(e) e.innerHTML=h; }

// Real-time phone input cleaner. Strips anything that isn't:
//   • digits 0-9
//   • optional leading +
//   • spaces, dashes, parentheses (display-only chars common in international formats)
// Also enforces minimum length feedback. The actual format is validated
// server-side; this is just to prevent obvious garbage like "asdf" or
// embedded letters that customers sometimes paste.
function validatePhoneInput(el) {
  if (!el) return;
  let v = el.value || '';
  // Allow only +, digits, space, dash, parentheses
  let cleaned = v.replace(/[^+\d\s\-\(\)]/g, '');
  // Only one + and only at the start
  if (cleaned.indexOf('+') > 0) cleaned = cleaned.replace(/\+/g, '');
  // Multiple + at start collapse to one
  cleaned = cleaned.replace(/^\++/, '+');
  if (cleaned !== v) el.value = cleaned;

  // Show inline error if too short, but only after they've typed something
  const errEl = $id('err_' + el.id.replace('b_', ''));
  if (errEl) {
    const digits = cleaned.replace(/\D/g, '');
    if (cleaned.length === 0) {
      errEl.textContent = '';
    } else if (digits.length < 7) {
      errEl.textContent = 'Phone number is too short.';
    } else if (digits.length > 15) {
      errEl.textContent = 'Phone number is too long.';
    } else {
      errEl.textContent = '';
    }
  }
}
function clearErrors() {
  document.querySelectorAll('.ferr').forEach(e => e.textContent = '');
  document.querySelectorAll('.fg input.error,.fg select.error').forEach(e => e.classList.remove('error'));
}
function showFieldError(f, msg) {
  const err = $id('err_' + f); if (err) err.textContent = msg;
  const inp = $id('b_' + f); if (inp) inp.classList.add('error');
}

// ── Swap nav to logged-in state after in-flow account creation ──
// Removes the "Sign In" link, inserts "My Account" into nav-links, and
// updates the mobile menu — so the user sees their session reflected
// without a full page reload.
function applyLoggedInNav() {
  const accountUrl = '/dashboard/';
  const logoutUrl  = '/auth/logout/';
  // 1. Hide / remove the desktop "Sign In" button if present
  document.querySelectorAll('.nav-sign').forEach(el => {
    if (/sign in/i.test(el.textContent)) el.remove();
  });
  // 2. Insert "My Account" pill into the desktop nav-links if missing
  const navLinks = document.querySelector('.nav-links');
  if (navLinks && !navLinks.querySelector('.nav-link-account')) {
    const li = document.createElement('li');
    li.innerHTML = '<a href="' + accountUrl + '" class="nav-link-account">👤 My Account</a>';
    navLinks.appendChild(li);
  }
  // 3. Update the mobile menu — replace "Sign In / Create Account" with My Account / Sign Out
  const mobileMenu = document.getElementById('mobileMenu');
  if (mobileMenu) {
    mobileMenu.querySelectorAll('a').forEach(a => {
      const t = a.textContent.trim();
      if (/sign in/i.test(t) || /create account/i.test(t)) a.remove();
    });
    if (!mobileMenu.querySelector('a[href="' + accountUrl + '"]')) {
      const div  = mobileMenu.querySelector('.mob-divider');
      const html =
        '<a href="' + accountUrl + '" onclick="closeMobileMenu()">👤 My Account</a>' +
        '<a href="' + logoutUrl  + '" onclick="closeMobileMenu()">🚪 Sign Out</a>';
      if (div) div.insertAdjacentHTML('afterend', html);
      else     mobileMenu.insertAdjacentHTML('beforeend', html);
    }
  }
}

// ── Toast notifications (replaces ugly alert() popups) ────
// Usage: toast('Saved!')                 → info (default)
//        toast('Booking failed', 'error')
//        toast('Payment received', 'success')
//        toast('Slow down a bit', 'warning')
// Stacks vertically on the bottom-right; auto-dismisses after 4 s.
function toast(message, type) {
  type = type || 'info';
  let host = document.getElementById('toastHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'toastHost';
    host.className = 'toast-host';
    document.body.appendChild(host);
  }
  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  const icons = {success:'✓', error:'✕', warning:'!', info:'i'};
  el.innerHTML =
    '<span class="toast-icon">' + (icons[type] || 'i') + '</span>' +
    '<span class="toast-msg"></span>' +
    '<button class="toast-close" aria-label="Close">×</button>';
  el.querySelector('.toast-msg').textContent = String(message);
  host.appendChild(el);
  // Slide-in
  requestAnimationFrame(() => el.classList.add('toast-in'));
  // Manual close
  el.querySelector('.toast-close').onclick = () => dismiss();
  // Auto dismiss
  const timer = setTimeout(dismiss, 4500);
  function dismiss() {
    clearTimeout(timer);
    el.classList.remove('toast-in');
    el.classList.add('toast-out');
    setTimeout(() => el.remove(), 250);
  }
}

// ── Mobile nav ────────────────────────────────────────────
function toggleMobileMenu() {
  const menu = $id('mobileMenu'); if (menu) menu.classList.toggle('open');
}
function closeMobileMenu() {
  const menu = $id('mobileMenu'); if (menu) menu.classList.remove('open');
}

// ── Booking modal ─────────────────────────────────────────
function openBookingModal() {
  // If the booking modal doesn't exist on this page (dashboard, blog, about, etc.)
  // redirect to the home page with ?book=1 — main.js will auto-open the modal there.
  const overlay = $id('bookingOverlay');
  if (!overlay) {
    window.location.href = '/?book=1#booking';
    return;
  }
  currentStep = 1; clearErrors(); updateStepUI();
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
  // Reset any invoice-flow customisations from a previous corporate booking
  // (the Step-2 dot is hidden + invoice action buttons appended). Without
  // this, a customer who books corporate first then normal would see a
  // broken step bar.
  const s2 = document.getElementById('s2');
  if (s2) s2.style.display = '';
  const prevInvoiceActions = document.getElementById('invoiceActions');
  if (prevInvoiceActions) prevInvoiceActions.remove();
  const prevInvoiceMeta = document.getElementById('invoiceMeta');
  if (prevInvoiceMeta) prevInvoiceMeta.remove();
  // Defeat browser autofill on password fields (Chrome ignores autocomplete=off,
  // but actively clearing fields after modal opens always works)
  ['b_password','b_password2'].forEach(id => { const el=$id(id); if(el) el.value=''; });
  // ── Booking windows start TOMORROW, not today ────────────────
  // We use ISO yyyy-mm-dd computed in local time so customers in any
  // timezone get the right minimum. Date inputs respect `min` and refuse
  // earlier values; we also clamp any pre-filled stale values.
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const tomorrowISO = tomorrow.getFullYear() + '-' +
    String(tomorrow.getMonth() + 1).padStart(2, '0') + '-' +
    String(tomorrow.getDate()).padStart(2, '0');
  // Day after tomorrow for return-date min (rentals are minimum 2 days)
  const dayAfter = new Date();
  dayAfter.setDate(dayAfter.getDate() + 2);
  const dayAfterISO = dayAfter.getFullYear() + '-' +
    String(dayAfter.getMonth() + 1).padStart(2, '0') + '-' +
    String(dayAfter.getDate()).padStart(2, '0');

  // Pickup-date inputs across all 3 booking flavours: rental, transfer, safari
  ['b_pickup_date','b_transfer_pickup_date','b_safari_pickup_date',
   'qs_pickup_date'].forEach(id => {
    const el = $id(id); if (!el) return;
    el.min = tomorrowISO;
    if (el.value && el.value < tomorrowISO) el.value = '';
  });
  // Return-date can't be earlier than the day after tomorrow (2-day min rental)
  ['b_return_date','qs_return_date'].forEach(id => {
    const el = $id(id); if (!el) return;
    el.min = dayAfterISO;
    if (el.value && el.value < dayAfterISO) el.value = '';
  });
  // Stamp form open time for bot time-trap (real humans take > 3s to fill)
  const ts = $id('b_form_started_at');
  if (ts && !ts.value) ts.value = String(Date.now());
}

function openBookingModalPrefilled() {
  // Safari vehicles can also be picked in the generic quick-search dropdown
  // (#qs_vehicle isn't filtered by category) — detect and redirect before
  // opening the modal, same fallback check as openBookingModalForCar.
  const qsVehicleId = val('qs_vehicle');
  const safariSel = $id('b_safari_vehicle');
  const isSafariCar = !!(qsVehicleId && safariSel &&
    Array.from(safariSel.options).some(o => o.value === String(qsVehicleId)));
  if (isSafariCar) {
    window.location.href = '/safari/';
    return;
  }
  openBookingModal();
  const map = {
    'b_vehicle':'qs_vehicle','b_pickup_location':'qs_pickup',
    'b_hotel_address':'qs_hotel','b_pickup_date':'qs_pickup_date',
    'b_pickup_time':'qs_pickup_time','b_return_date':'qs_return_date',
    'b_return_time':'qs_return_time'
  };
  Object.entries(map).forEach(([d,s]) => {
    const se=$id(s), de=$id(d);
    if (se && de && se.value) de.value = se.value;
  });
  toggleHotelField(); updatePricingPreview();
}

function openBookingModalForCar(vehicleId) {
  // Detect whether this is a safari-only car — checked FIRST, before the
  // modal-presence redirect below, so this also works on pages (like the
  // vehicle detail page) where the modal doesn't exist at all. Primary
  // signal is VEHICLES[].category (works on any page); falls back to the
  // safari select's options when category isn't available but the modal
  // (and its #b_safari_vehicle select) happens to be present.
  const v = (VEHICLES || []).find(x => String(x.id) === String(vehicleId));
  let isSafariCar = !!(v && v.category === 'safari');
  const safariSel = $id('b_safari_vehicle');
  if (!isSafariCar && safariSel) {
    isSafariCar = Array.from(safariSel.options).some(o => o.value === String(vehicleId));
  }
  if (isSafariCar) {
    // Safari now lives on its own indexable page — send it there instead
    // of pivoting the modal into Safari mode.
    window.location.href = '/safari/';
    return;
  }

  // Vehicle detail page lives at /cars/<slug>/ — modal isn't there.
  // Redirect home with vehicle pre-selected.
  if (!$id('bookingOverlay')) {
    window.location.href = '/?book=1&car=' + encodeURIComponent(vehicleId) + '#booking';
    return;
  }
  openBookingModal();

  const sel = $id('b_vehicle');
  if (sel) { sel.value = String(vehicleId); updatePricingPreview(); }
}

// Service card helper — sets hire type and opens modal
function openBookingModalWithType(type) {
  // Safari now lives on its own indexable page — send it there instead of
  // opening the modal, regardless of whether the modal exists on this page.
  // All other types (normal/corporate/transfer) fall through unchanged.
  if (type === 'safari') { window.location.href = '/safari/'; return; }
  // If modal isn't on this page, redirect home with type pre-selected
  if (!$id('bookingOverlay')) {
    window.location.href = '/?book=1&type=' + encodeURIComponent(type) + '#booking';
    return;
  }
  openBookingModal();
  // Use setHireType so pills, hidden input, and field visibility all update.
  // Falls back gracefully if setHireType isn't defined yet (early page load).
  if (typeof setHireType === 'function') {
    setHireType(type);
  } else {
    const sel = $id('b_hire_type');
    if (sel) { sel.value = type; updatePricingPreview(); }
  }
}

function closeBookingModal() {
  const overlay = $id('bookingOverlay'); if (overlay) overlay.classList.remove('open');
  document.body.style.overflow = '';
  // Remove the payment-step Back trap if it was installed — otherwise a
  // popstate handler would linger after the modal is gone.
  if (typeof _removePaymentBackTrap === 'function') _removePaymentBackTrap();
}

// ── Field toggles ─────────────────────────────────────────
// Driver choice is now a dedicated select field next to Hire Type.
// The hidden checkbox #b_with_driver is kept in sync so the existing
// form submit + pricing preview logic continues to work unchanged.
// ── Driver checkbox toggled on/off ─────────────────────────
// New behaviour: driver is now a checkbox under Optional Add-ons.
// We keep the legacy hidden b_driver_option in sync ('self' / 'driver')
// since the server-side code reads either field. Cyan styling on the
// .addon-checkbox label is driven by :has(input:checked) in CSS.
// ── Driver dropdown changed ─────────────────────────────
// Driver is once again a <select>: 'self' (default) or 'driver'.
// The hidden b_with_driver checkbox is kept in sync so any older
// server-side code that reads either field still works.
function onDriverOptionChange() {
  const sel      = $id('b_driver_option');
  const checkbox = $id('b_with_driver');
  const choice   = sel ? sel.value : 'self';
  if (checkbox) checkbox.checked = (choice === 'driver');
  updatePricingPreview();
}

// Legacy alias kept so any older code that called onDriverToggle still works
function onDriverToggle() { onDriverOptionChange(); }

// ── Set hire type (called from the modal pill buttons) ─────
// Updates: visual active class on pills, hidden b_hire_type input,
// swap rental vs transfer field sections, then triggers downstream filters.
function setHireType(type) {
  type = type || 'normal';
  // Update pill visual states
  document.querySelectorAll('#modalHireTabs .hire-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.type === type);
  });
  // Update homepage hero tabs to match
  document.querySelectorAll('#hireTabs .tab').forEach(t => {
    t.classList.toggle('active', t.dataset.type === type);
  });
  // Update hidden input (server reads this)
  const hidden = $id('b_hire_type');
  if (hidden) hidden.value = type;

  // ── Swap which field section is visible ───────────────────
  // Three modes:
  //   transfer → airport transfer form (no rental/safari fields)
  //   safari   → safari package form (no rental/transfer fields)
  //   else     → standard rental form (no transfer/safari fields)
  // We toggle CSS display + the `required` attribute on inputs so HTML5
  // validation only checks the visible set.
  const isTransfer = (type === 'transfer');
  const isSafari   = (type === 'safari');
  const isRental   = !(isTransfer || isSafari);

  const rental   = $id('rentalFields');
  const transfer = $id('transferFields');
  const safari   = $id('safariFields');
  if (rental)   rental.style.display   = isRental   ? '' : 'none';
  if (transfer) transfer.style.display = isTransfer ? '' : 'none';
  if (safari)   safari.style.display   = isSafari   ? '' : 'none';

  // Show/hide corporate-specific fields block. Live INSIDE rentalFields,
  // visible only when corporate is the active hire type. On mobile the
  // user may be scrolled past the new fields when they appear — scroll
  // them into view so they're visible and obvious.
  const corporate = $id('corporateFields');
  if (corporate) {
    const wasHidden = corporate.style.display === 'none';
    corporate.style.display = (type === 'corporate') ? '' : 'none';
    if (type === 'corporate' && wasHidden) {
      // Defer so the layout settles (display:'' transitions take effect)
      setTimeout(() => {
        const companyNameInput = $id('b_company_name');
        if (companyNameInput) {
          companyNameInput.scrollIntoView({behavior: 'smooth', block: 'center'});
          // Focus the input so mobile keyboard pops up — makes it
          // immediately clear this is where the user should type
          companyNameInput.focus({preventScroll: true});
        }
      }, 60);
    }
  }

  // Toggle required attribute per visible section
  // Rental fields
  ['b_vehicle','b_pickup_location','b_pickup_date','b_pickup_time',
   'b_return_date','b_return_time'].forEach(id => {
    const el = $id(id); if (!el) return;
    if (isRental) el.setAttribute('required', '');
    else          el.removeAttribute('required');
  });
  // Transfer fields
  ['b_transfer_direction','b_transfer_car_type','b_transfer_location',
   'b_transfer_pickup_date','b_transfer_pickup_time'].forEach(id => {
    const el = $id(id); if (!el) return;
    if (isTransfer) el.setAttribute('required', '');
    else            el.removeAttribute('required');
  });
  // Safari fields
  ['b_safari_vehicle','b_safari_pickup_date','b_safari_pickup_time',
   'b_safari_pickup_location'].forEach(id => {
    const el = $id(id); if (!el) return;
    if (isSafari) el.setAttribute('required', '');
    else          el.removeAttribute('required');
  });

  // Per-mode init
  if (isTransfer && typeof onTransferDirectionChange === 'function') {
    onTransferDirectionChange();
    updateTransferQuote();
  }
  if (isSafari && typeof loadSafariDestinations === 'function') {
    loadSafariDestinations();   // lazy-load destination list on first show
  }

  // Corporate hire requires a 5-day minimum rental period. We expose this
  // as a hint near the return-date field. The actual `min` attr on the
  // return-date input gets updated whenever the pickup date changes
  // (see _enforceCorporateMinDays below). Server also rejects <5 days.
  _enforceCorporateMinDays();

  // Run downstream filters (rental vehicle filter etc.)
  if (typeof onHireTypeChange === 'function') onHireTypeChange();
  else updatePricingPreview();
}

// Corporate Hire requires a minimum rental period of 5 days. We enforce
// this in 3 places:
//  (1) The return-date input's `min` attribute becomes pickup + 5 days
//  (2) A hint appears below the return-date field
//  (3) The server rejects sub-5-day corporate bookings (forms.py)
// Called from setHireType and from any onChange of pickup_date.
function _enforceCorporateMinDays() {
  const hire = val('b_hire_type');
  const isCorporate = (hire === 'corporate');
  const pickupEl = $id('b_pickup_date');
  const returnEl = $id('b_return_date');
  let hintEl = $id('corporateMinHint');

  if (!returnEl) return;

  // Tomorrow ISO (always at least tomorrow for return-date min)
  const dayAfter = new Date();
  dayAfter.setDate(dayAfter.getDate() + 2);
  const dayAfterISO = dayAfter.getFullYear() + '-' +
    String(dayAfter.getMonth() + 1).padStart(2, '0') + '-' +
    String(dayAfter.getDate()).padStart(2, '0');

  if (!isCorporate) {
    returnEl.min = dayAfterISO;
    if (hintEl) hintEl.style.display = 'none';
    return;
  }

  // Compute: pickup + 5 days. If pickup not set yet, use tomorrow + 5.
  let baseDate;
  if (pickupEl && pickupEl.value) {
    baseDate = new Date(pickupEl.value + 'T00:00:00');
  } else {
    baseDate = new Date();
    baseDate.setDate(baseDate.getDate() + 1);
  }
  baseDate.setDate(baseDate.getDate() + 5);
  const minISO = baseDate.getFullYear() + '-' +
    String(baseDate.getMonth() + 1).padStart(2, '0') + '-' +
    String(baseDate.getDate()).padStart(2, '0');
  returnEl.min = minISO;

  // If the existing return value is below the new minimum, bump it.
  if (returnEl.value && returnEl.value < minISO) {
    returnEl.value = minISO;
    if (typeof updatePricingPreview === 'function') updatePricingPreview();
  }

  // Inject/show hint
  if (!hintEl) {
    hintEl = document.createElement('div');
    hintEl.id = 'corporateMinHint';
    hintEl.style.cssText = 'font-size:.74rem;color:var(--blue);margin-top:4px;line-height:1.4';
    hintEl.innerHTML = 'ℹ️ Corporate Hire requires a minimum of <strong>5 days</strong>.';
    // Place right after the return-date input
    const parent = returnEl.parentNode;
    if (parent) parent.appendChild(hintEl);
  }
  hintEl.style.display = '';
}

// ── Hire type changed — apply Safari Package vehicle filter ───────
// Safari Package may only be hired with safari-ready vehicles.
// We hide all non-safari options when 'safari' is picked, and restore
// them when any other hire type is picked. If the currently-selected
// vehicle is not safari-ready and the user picks Safari, clear it.
//
// Airport Transfer ('transfer') will swap the entire form layout in
// Stage 2 — for now this function just keeps the safari filter behaviour.
function onHireTypeChange() {
  const hire = val('b_hire_type');
  const veh  = $id('b_vehicle');

  // ── Driver field: Safari Package always includes a driver, so we hide
  // the Self/With-Driver dropdown and show a static "included" note.
  // For all other hire types, the dropdown is the customer's choice.
  const driverWrap = $id('driverFieldWrap');
  const safariNote = $id('safariDriverNote');
  const withDriverCheckbox = $id('b_with_driver');
  const driverSel  = $id('b_driver_option');
  if (hire === 'safari') {
    if (driverWrap) driverWrap.style.display = 'none';
    if (safariNote) safariNote.style.display = '';
    // Force "with driver" so server-side billing reflects this
    if (driverSel) driverSel.value = 'driver';
    if (withDriverCheckbox) withDriverCheckbox.checked = true;
  } else {
    if (driverWrap) driverWrap.style.display = '';
    if (safariNote) safariNote.style.display = 'none';
    // Don't reset their previous choice — they may have ticked driver before
  }

  if (!veh) { updatePricingPreview(); return; }

  // Vehicle visibility per hire type:
  //   safari      → ONLY safari-ready cars shown
  //   normal/etc. → ALL cars EXCEPT safari-ready (safari cars are a
  //                 specialised, priced-per-destination product)
  const wantSafariOnly = (hire === 'safari');
  let clearedSelection = false;

  Array.from(veh.options).forEach(opt => {
    if (!opt.value) { opt.hidden = false; return; }   // keep "— Select Vehicle —"
    const cat = opt.dataset.category || '';
    const isSafari = (cat === 'safari');
    if (wantSafariOnly) {
      opt.hidden = !isSafari;             // safari mode: hide non-safari
    } else {
      opt.hidden = isSafari;              // any other mode: hide safari cars
    }
    if (opt.selected && opt.hidden) {
      veh.value = '';
      clearedSelection = true;
    }
  });

  if (clearedSelection) {
    const errEl = $id('err_vehicle');
    if (errEl) {
      errEl.textContent = wantSafariOnly
        ? 'Safari Package requires a Safari-Ready vehicle. Please pick one from the list.'
        : 'That vehicle is only available under the Safari Package hire type. Please pick a different vehicle.';
    }
  } else {
    const errEl = $id('err_vehicle');
    if (errEl) errEl.textContent = '';
  }
  updatePricingPreview();
}

// ════════════════════════════════════════════════════════════════════
//  AIRPORT TRANSFER — quote logic & UI helpers
// ════════════════════════════════════════════════════════════════════

// Detect zone from a location string using TRANSFER_CONSTS.zone_locations.
// Substring match in either direction so partial input also matches.
function detectTransferZone(locText) {
  if (!locText || !TRANSFER_CONSTS.zone_locations) return '';
  const needle = locText.trim().toLowerCase();
  if (!needle) return '';
  const zones = TRANSFER_CONSTS.zone_locations;
  for (const zone in zones) {
    for (const loc of zones[zone]) {
      if (loc.includes(needle) || needle.includes(loc)) return zone;
    }
  }
  return '';
}

// True if pickup time string "HH:MM" falls in the night surcharge window.
function isTransferNightPickup(timeStr) {
  if (!timeStr) return false;
  const [h] = timeStr.split(':').map(s => parseInt(s, 10));
  if (isNaN(h)) return false;
  const start = TRANSFER_CONSTS.night_start || 22;
  const end   = TRANSFER_CONSTS.night_end || 6;
  return h >= start || h < end;
}

// Direction toggle changes the location label between Destination/Pickup
function onTransferDirectionChange() {
  const dir = val('b_transfer_direction') || 'FROM';
  const lbl = $id('transferLocationLabel');
  if (lbl) {
    lbl.innerHTML = (dir === 'FROM')
      ? 'Destination <span class="req">*</span>'
      : 'Pickup Location <span class="req">*</span>';
  }
  updateTransferQuote();
}

// Location selected — auto-detect zone and update the quote
function onTransferLocationChange() {
  const loc = val('b_transfer_location');
  const zone = detectTransferZone(loc);
  const hint = $id('zoneHint');
  if (hint) {
    if (zone && TRANSFER_CONSTS.zone_labels) {
      hint.style.display = '';
      hint.textContent = `Zone: ${TRANSFER_CONSTS.zone_labels[zone] || zone}`;
    } else {
      hint.style.display = 'none';
    }
  }
  updateTransferQuote();
}

// Recompute the live quote and update the price preview block.
// Mirrors the server-side airport_transfer.quote() function — both are
// used: this for instant UI, server for the locked-in price at booking.
// USD is the base currency. KES & EUR are computed for display.
function updateTransferQuote() {
  const carType  = val('b_transfer_car_type');
  const loc      = val('b_transfer_location');
  const pickTime = val('b_transfer_pickup_time') || '08:00';
  const zone     = detectTransferZone(loc);
  const preview  = $id('transferPricePreview');

  if (!preview) return;
  if (!carType || !zone || !TRANSFER_CONSTS.prices_usd) {
    preview.style.display = 'none';
    return;
  }

  const baseUsd = TRANSFER_CONSTS.prices_usd[`${zone}|${carType}`];
  if (baseUsd == null) { preview.style.display = 'none'; return; }

  const isNight  = isTransferNightPickup(pickTime);
  const nightUsd = isNight ? (TRANSFER_CONSTS.night_usd || 0) : 0;
  const totalUsd = baseUsd + nightUsd;
  const totalKes = totalUsd * (TRANSFER_CONSTS.kes_per_usd || 130);
  const totalEur = totalUsd * (TRANSFER_CONSTS.eur_per_usd || 0.93);

  preview.style.display = '';
  setText('tpp_zone_label', TRANSFER_CONSTS.zone_labels[zone] || zone);
  const carLabels = {economy:'Economy', midsize:'Mid-size', luxury:'Luxury', van:'Van/Group'};
  setText('tpp_car_label', carLabels[carType] || carType);
  setText('tpp_base', `$${baseUsd}`);

  const nightRow = $id('tpp_night_row');
  if (isNight) {
    if (nightRow) nightRow.style.display = '';
    setText('tpp_night', `+ $${nightUsd}`);
  } else {
    if (nightRow) nightRow.style.display = 'none';
  }

  setText('tpp_total_usd', `$${totalUsd.toFixed(2)}`);
  setText('tpp_total_kes', `KES ${Math.round(totalKes).toLocaleString()}`);
  setText('tpp_total_eur', `€${totalEur.toFixed(2)}`);
  setText('tpp_total_pay', `$${totalUsd.toFixed(2)} (≈ KES ${Math.round(totalKes).toLocaleString()})`);
}


// ════════════════════════════════════════════════════════════════════
//  SAFARI PACKAGE — destinations, chips, live quote
// ════════════════════════════════════════════════════════════════════

// Cached safari destination list (fetched once on first safari mode entry).
let SAFARI_DESTS = null;
// Customer's currently selected destination IDs, in pick order.
let safariSelected = [];
// Per-destination day overrides — keyed by destination ID, value = days.
let safariDays = {};

// Load destinations from server. Idempotent — only fetches once per page.
function loadSafariDestinations() {
  if (SAFARI_DESTS !== null) return;          // already loaded
  fetch('/safari/destinations/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) { SAFARI_DESTS = []; return; }
      SAFARI_DESTS = data.destinations || [];
      renderSafariDestList();
    })
    .catch(() => { SAFARI_DESTS = []; });
}

// Render destination chips. Each chip toggles on click; selected chips
// expand to show a days slider.
function renderSafariDestList() {
  const wrap = $id('safariDestList');
  if (!wrap) return;
  if (!SAFARI_DESTS || !SAFARI_DESTS.length) {
    wrap.innerHTML = '<div style="color:var(--muted);font-size:.82rem">No safari destinations available right now. Please WhatsApp us to book.</div>';
    return;
  }
  // Render chips WITHOUT per-chip onclick — we use a single delegated
  // listener on the wrap (attached once on first render). Per-chip
  // handlers got dropped when innerHTML rewrote the DOM mid-tap,
  // causing intermittent "tap doesn't work" on mobile.
  wrap.innerHTML = SAFARI_DESTS.map(d => {
    const picked = safariSelected.includes(d.id);
    const minDays = d.min_days || 1;
    const days = Math.max(safariDays[d.id] || d.days, minDays);
    return `
      <div class="safari-dest ${picked ? 'picked' : ''}" data-id="${d.id}" role="button" tabindex="0" aria-pressed="${picked}">
        <div class="sd-head">
          <div class="sd-name">${d.short_name}</div>
          <div class="sd-meta">${d.distance_km} km · min ${minDays} day${minDays!==1?'s':''}</div>
        </div>
        ${d.description ? `<div class="sd-desc">${d.description}</div>` : ''}
        ${picked ? `
          <div class="sd-days" data-no-toggle="1">
            <label for="days_${d.id}" style="font-size:.74rem;color:var(--muted)">Days here (min ${minDays}):</label>
            <input type="number" id="days_${d.id}" min="${minDays}" max="14" value="${days}"
                   oninput="setSafariDays(${d.id}, this.value)"
                   onchange="setSafariDays(${d.id}, this.value)"
                   data-no-toggle="1"
                   style="width:70px;padding:4px 8px;font-weight:700"/>
          </div>
        ` : ''}
      </div>
    `;
  }).join('');

  // Attach delegated listener ONCE — flagged on the wrap so we don't
  // double-bind on re-render. The listener walks up the DOM from the
  // tapped element to find the .safari-dest ancestor, then toggles.
  if (!wrap._safariBound) {
    wrap._safariBound = true;
    wrap.addEventListener('click', function(ev) {
      // Bail if the tap originated inside .sd-days (days input or its label).
      // Both have data-no-toggle="1" so we can detect them without coupling to
      // class names. closest() walks up the tree from the actual target.
      if (ev.target.closest('[data-no-toggle]')) return;
      const chip = ev.target.closest('.safari-dest');
      if (!chip || !wrap.contains(chip)) return;
      const id = parseInt(chip.dataset.id, 10);
      if (!isNaN(id)) toggleSafariDest(id);
    });
    // Keyboard a11y — Enter or Space on a focused chip toggles
    wrap.addEventListener('keydown', function(ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      if (ev.target.closest('[data-no-toggle]')) return;
      const chip = ev.target.closest('.safari-dest');
      if (!chip) return;
      ev.preventDefault();
      const id = parseInt(chip.dataset.id, 10);
      if (!isNaN(id)) toggleSafariDest(id);
    });
  }
}

function toggleSafariDest(destId) {
  const idx = safariSelected.indexOf(destId);
  if (idx >= 0) {
    safariSelected.splice(idx, 1);
    delete safariDays[destId];
  } else {
    safariSelected.push(destId);
    const d = (SAFARI_DESTS || []).find(x => x.id === destId);
    if (d) {
      // Initial value = max(recommended, min) so we never start below the
      // physical minimum for that distance.
      const minDays = d.min_days || 1;
      safariDays[destId] = Math.max(d.days || minDays, minDays);
    }
  }
  renderSafariDestList();
  updateSafariQuote();
}

function setSafariDays(destId, val) {
  let n = parseInt(val, 10);
  // Look up destination's min based on distance
  const d = (SAFARI_DESTS || []).find(x => x.id === destId);
  const minDays = (d && d.min_days) ? d.min_days : 1;
  if (isNaN(n) || n < minDays) n = minDays;
  if (n > 14) n = 14;
  safariDays[destId] = n;
  // Debounce — typing "12" shouldn't fire two requests (one for "1", one for "12").
  // 250ms is below the threshold where users perceive lag.
  clearTimeout(window._safariQuoteTimer);
  window._safariQuoteTimer = setTimeout(updateSafariQuote, 250);
}

// Hit the server for a fresh quote. Server is source of truth — we don't
// recompute in JS to avoid prices drifting from the admin.
function updateSafariQuote() {
  const vehicleId = val('b_safari_vehicle');
  const preview = $id('safariPricePreview');
  if (!preview) return;
  if (!vehicleId || !safariSelected.length) {
    preview.style.display = 'none';
    return;
  }

  const fd = new FormData();
  fd.append('csrfmiddlewaretoken', getCsrf());
  fd.append('vehicle_id', vehicleId);
  fd.append('destinations', safariSelected.join(','));
  safariSelected.forEach(id => {
    if (safariDays[id]) fd.append(`days_${id}`, safariDays[id]);
  });

  fetch('/safari/quote/', { method: 'POST', body: fd, credentials: 'same-origin' })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) {
        preview.style.display = 'none';
        return;
      }
      const rowsHtml = data.breakdown.map(b => `
        <div class="pp-row">
          <span>${b.name} (${b.days} day${b.days!==1?'s':''} × $${b.daily_usd.toFixed(2)})</span>
          <span>$${b.subtotal_usd.toFixed(2)}</span>
        </div>
      `).join('');
      const breakdownDiv = $id('safari_breakdown_rows');
      if (breakdownDiv) breakdownDiv.innerHTML = rowsHtml;
      setText('spp_total_days', data.total_days);
      setText('spp_total_usd', `$${data.total_usd.toFixed(2)}`);
      setText('spp_total_kes', `KES ${data.total_kes.toLocaleString()}`);
      setText('spp_total_eur', `€${data.total_eur.toFixed(2)}`);
      setText('spp_total_pay', `$${data.total_usd.toFixed(2)} (≈ KES ${data.total_kes.toLocaleString()})`);
      preview.style.display = '';
    })
    .catch(() => { preview.style.display = 'none'; });
}

// Show/hide hotel address field for safari pickup
function onSafariPickupChange() {
  const loc = val('b_safari_pickup_location');
  const wrap = $id('safariHotelWrap');
  if (wrap) wrap.style.display = (loc === 'HOTEL' || loc === 'other') ? '' : 'none';
}


// ── Pickup location toggle: shows hotel OR custom address field ───
function toggleHotelField() {
  const loc = val('b_pickup_location');
  const hotel  = $id('hotelFieldWrap');
  const custom = $id('customPickupWrap');
  if (hotel)  hotel.style.display  = (loc === 'HOTEL') ? '' : 'none';
  if (custom) custom.style.display = (loc === 'other') ? '' : 'none';
}

function toggleAccSection() {
  accOpen = !accOpen;
  const body=$id('accBody'), chev=$id('accChevron');
  if (body) body.classList.toggle('open', accOpen);
  if (chev) chev.classList.toggle('open', accOpen);
}

// ── Live pricing preview — includes driver fee ────────────
function updatePricingPreview() {
  // Whenever pickup/return changes, ensure corporate's 5-day rule is fresh
  // (return-date min depends on pickup date). No-op for non-corporate.
  if (typeof _enforceCorporateMinDays === 'function') _enforceCorporateMinDays();

  const vehicleId = parseInt(val('b_vehicle'));
  const pDate = val('b_pickup_date');
  const rDate = val('b_return_date');
  // Driver is a SELECT now: 'self' or 'driver'.
  const driverChoice = val('b_driver_option') || 'self';
  const withDriver   = (driverChoice === 'driver');
  const babySeat     = val('b_baby_seat');  // boolean from checkbox

  // Always update the dropdown's "With Driver" option label to show the
  // current vehicle's driver fee — even before pickup/return dates exist.
  // This way the customer sees an accurate price as soon as they pick a car.
  if (vehicleId) {
    const vehLookup = VEHICLES.find(x => x.id === vehicleId);
    if (vehLookup) {
      const opt = $id('driverWithOption');
      if (opt) opt.textContent = `With Driver (+$${vehLookup.driver}/day)`;
      setText('driverFeeInline', vehLookup.driver);
    }
  } else {
    // No vehicle picked yet — reset the option text
    const opt = $id('driverWithOption');
    if (opt) opt.textContent = 'With Driver (select a vehicle to see price)';
    setText('driverFeeInline', '0');
  }

  const preview = $id('pricePreview');
  if (!vehicleId || !pDate || !rDate) { if (preview) preview.style.display = 'none'; return; }
  const v = VEHICLES.find(x => x.id === vehicleId);
  if (!v) return;
  // Calendar-day billing: both pickup and return dates count, floored to a
  // 2-day minimum. Must stay identical to core/views.py's booking_submit().
  let days = Math.round((new Date(rDate) - new Date(pDate)) / 86400000) + 1;
  if (isNaN(days)) days = 2;
  days = Math.max(days, 2);
  const base = parseFloat(v.usd) * days;
  const driverFee = withDriver ? parseFloat(v.driver) * days : 0;
  const babyFee   = babySeat ? 10 : 0;  // $10 flat for the whole trip
  const total = base + driverFee + babyFee;
  if (preview) preview.style.display = '';
  setText('pp_rate',  `$${v.usd}/day`);
  setText('pp_days',  `${days} day${days !== 1 ? 's' : ''}`);
  const dRow = $id('pp_driver_row');
  if (withDriver) {
    if (dRow) dRow.style.display = '';
    setText('pp_driver', `$${driverFee.toFixed(2)}`);
  } else {
    if (dRow) dRow.style.display = 'none';
  }
  // Baby seat row (optional)
  const bRow = $id('pp_baby_row');
  if (babySeat) {
    if (bRow) bRow.style.display = '';
    setText('pp_baby', `$${babyFee.toFixed(2)}`);
  } else {
    if (bRow) bRow.style.display = 'none';
  }
  setText('pp_total', `$${total.toFixed(2)} / €${(total*0.92).toFixed(2)} / KES ${Math.round(total*130).toLocaleString()}`);
  // Update M-Pesa amount display
  setText('mpesa_amount_disp', `KES ${Math.round(total*130).toLocaleString()}`);
}

// ── Step UI ───────────────────────────────────────────────
function updateStepUI() {
  for (let i = 1; i <= 3; i++) {
    const dot=$id('s'+i), fs=$id('fs'+i);
    if (dot) dot.className = 'step'+(i===currentStep?' active':i<currentStep?' done':'');
    if (fs)  fs.className  = 'form-step'+(i===currentStep?' active':'');
  }
  const back=$id('btnBack'), next=$id('btnNext');
  if (back) back.style.display = (currentStep>1&&currentStep<3) ? '' : 'none';
  if (next) {
    // Step 2: pay buttons are inline; hide the footer Next entirely.
    // Step 3: terminal screen, no buttons.
    if (currentStep===2 || currentStep===3) {
      next.style.display='none';
    } else {
      next.style.display='';
      next.textContent = 'Continue →';
    }
  }
  const titles=['Your Booking Details','Secure Payment','Booking Confirmed'];
  setText('modalTitle', titles[currentStep-1]);

  // Install / remove the browser-Back trap depending on the step.
  // Step 2 (payment) gets a trap; any other step removes it.
  if (currentStep === 2) {
    _installPaymentBackTrap();
  } else {
    _removePaymentBackTrap();
  }

  // Scroll modal body to top when changing step — so user sees the start
  // of the new step (payment summary, not the buttons at the bottom)
  setTimeout(() => {
    const body = document.querySelector('.modal-body');
    if (body) body.scrollTop = 0;
  }, 0);
}

// ── Browser-Back trap for the payment step ────────────────────────
// Problem: once a customer is on the payment step, browser Back behaved
// unpredictably — sometimes restoring the form, sometimes landing on a
// blank page, sometimes letting them create a duplicate booking.
//
// Solution: a deterministic trap.
//  • We push a history sentinel when Step 2 opens.
//  • When the customer presses Back, popstate fires:
//     – If the booking is < 10 min old → we treat Back as "edit my
//       booking": close to Step 1 with the form intact. The next submit
//       carries edit_ref so the SAME booking is updated, no duplicate.
//     – If the booking is ≥ 10 min old → we re-push the sentinel so the
//       customer stays on the payment page, and show a short notice.
//       (After 10 min the booking is "settled" — same window as the
//        reminder email — and silently editing it is more confusing
//        than helpful.)
//  • Leaving Step 2 (paying, or going back to Step 1 via the in-modal
//    Back button) removes the trap.
let _payBackTrapInstalled = false;
let _payBackTrapHandler = null;

function _bookingAgeMs() {
  // pendingBooking carries no timestamp itself; we read the sessionStorage
  // snapshot's ts. Falls back to "fresh" (0) if not found.
  try {
    const persisted = sessionStorage.getItem('munwan_pending_booking');
    if (persisted) {
      const parsed = JSON.parse(persisted);
      if (parsed && parsed.ts) return Date.now() - parsed.ts;
    }
  } catch (_) {}
  return 0;
}

function _installPaymentBackTrap() {
  if (_payBackTrapInstalled) return;
  _payBackTrapInstalled = true;

  // Push a sentinel entry so the FIRST Back press lands here, not on the
  // previous page. Without this, one Back press would leave the site.
  try { history.pushState({ payTrap: true }, '', window.location.href); }
  catch (_) {}

  _payBackTrapHandler = function(ev) {
    // Only act while we're actually on the payment step.
    if (currentStep !== 2) return;

    const ageMs = _bookingAgeMs();
    const TEN_MIN = 10 * 60 * 1000;

    if (ageMs < TEN_MIN) {
      // Fresh booking → Back means "let me edit". Drop to Step 1 with the
      // form still populated. pendingBooking stays set, so the re-submit
      // updates the existing booking (edit_ref) instead of creating one.
      currentStep = 1;
      updateStepUI();   // this also removes the trap (currentStep !== 2)
      if (typeof toast === 'function') {
        toast('You can edit your booking. Changes update it — no new booking is created.', 'info');
      }
    } else {
      // Settled booking (≥10 min) → trap on the payment page. Re-push the
      // sentinel so this Back press is absorbed, and tell the customer.
      try { history.pushState({ payTrap: true }, '', window.location.href); }
      catch (_) {}
      if (!document.getElementById('payTrapNotice')) {
        const note = document.createElement('div');
        note.id = 'payTrapNotice';
        note.textContent = 'Please complete payment, or close this window to start a new booking.';
        note.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);' +
          'background:#1F2937;color:#fff;padding:11px 18px;border-radius:8px;' +
          'font-family:Poppins,sans-serif;font-size:.85rem;font-weight:600;' +
          'box-shadow:0 8px 24px rgba(0,0,0,.3);z-index:99999;max-width:90vw;text-align:center';
        document.body.appendChild(note);
        setTimeout(function(){
          note.style.transition = 'opacity .4s';
          note.style.opacity = '0';
          setTimeout(function(){ if (note.parentNode) note.parentNode.removeChild(note); }, 450);
        }, 2800);
      }
    }
  };
  window.addEventListener('popstate', _payBackTrapHandler);
}

function _removePaymentBackTrap() {
  if (!_payBackTrapInstalled) return;
  _payBackTrapInstalled = false;
  if (_payBackTrapHandler) {
    window.removeEventListener('popstate', _payBackTrapHandler);
    _payBackTrapHandler = null;
  }
}

function nextStep() { if (currentStep===1) submitStep1(); }
function prevStep()  { if (currentStep>1) { currentStep--; updateStepUI(); } }

// ── Step 1 ────────────────────────────────────────────────
async function submitStep1() {
  clearErrors();

  const hireType = val('b_hire_type') || 'normal';

  // ── Airport Transfer has its own field set & validation ─────
  if (hireType === 'transfer') {
    return submitStep1Transfer();
  }
  if (hireType === 'safari') {
    return submitStep1Safari();
  }

  const fields = {
    first_name:      val('b_first_name'),
    last_name:       val('b_last_name'),
    email:           val('b_email'),
    phone:           val('b_phone'),
    nationality:     val('b_nationality'),
    vehicle:         val('b_vehicle'),
    hire_type:       val('b_hire_type') || 'self',
    with_driver:     val('b_with_driver') ? 'on' : '',
    baby_seat:       val('b_baby_seat') ? 'on' : '',
    pickup_location: val('b_pickup_location'),
    hotel_address:   val('b_hotel_address'),
    dropoff_location:val('b_dropoff'),
    pickup_date:     val('b_pickup_date'),
    pickup_time:     val('b_pickup_time'),
    return_date:     val('b_return_date'),
    return_time:     val('b_return_time'),
    // Corporate fields — sent on every submit; server only requires them
    // when hire_type='corporate'.
    company_name:    val('b_company_name'),
    company_kra_pin: val('b_company_kra_pin'),
    company_address: val('b_company_address'),
    create_account:  accOpen ? 'on' : '',
    password:        val('b_password'),
    password_confirm:val('b_password2'),
    terms_accepted:  val('b_terms_accepted') ? 'on' : '',
    // If a booking has already been created in this session (user clicked
    // Continue, reached payment, then Back to edit), pass its reference so
    // the server UPDATES that booking instead of creating a duplicate.
    // pendingBooking is set in the data.ok branch below — see step 2 onward.
    edit_ref:        (pendingBooking && pendingBooking.reference) || '',
    // Bot traps
    website:         val('b_website') || '',
    form_started_at: val('b_form_started_at') || '',
  };
  let hasError = false;
  ['first_name','last_name','email','phone','vehicle','pickup_location',
   'pickup_date','pickup_time','return_date','return_time'].forEach(f => {
    if (!fields[f] || !fields[f].toString().trim()) {
      showFieldError(f, 'This field is required.'); hasError = true;
    }
  });

  // ── Email must contain "@" and a "." after it ────────────
  // Lightweight check that catches the common mistakes without being too strict.
  if (fields.email && fields.email.trim()) {
    const e = fields.email.trim();
    if (!e.includes('@') || e.indexOf('@') === e.length - 1 || !e.includes('.')) {
      showFieldError('email', 'Please enter a valid email address (must contain @ and a . after it, e.g. you@example.com).');
      hasError = true;
    }
  }

  if (fields.pickup_location==='HOTEL' && !fields.hotel_address.trim()) {
    showFieldError('hotel_address','Hotel address required.'); hasError=true;
  }
  // Custom pickup location requires the user to type their address
  if (fields.pickup_location==='other') {
    fields.custom_pickup = val('b_custom_pickup');
    if (!fields.custom_pickup || !fields.custom_pickup.trim()) {
      showFieldError('custom_pickup', 'Please enter your pick-up address.');
      hasError = true;
    } else {
      // The server expects the chosen pickup_location code OR a free-text
      // address in hotel_address. Reuse hotel_address to carry the custom
      // address — server treats it as delivery instructions either way.
      fields.hotel_address = fields.custom_pickup;
    }
  }

  // ── Return date must be after pick-up (normal/corporate only) ─────
  // This code path is unreachable for Airport Transfer (branches into
  // submitStep1Transfer() above) and Safari (submitStep1Safari()), so
  // same-day transfers/safaris are unaffected. Minimum billed period is
  // 2 calendar days (see core/forms.py's clean() and views.py's
  // booking_submit()).
  if (fields.pickup_date && fields.return_date && fields.return_date <= fields.pickup_date) {
    toast('Return date must be after the pick-up date. Minimum rental is 2 days.', 'error');
    showFieldError('return_date', 'Return date must be after the pick-up date.');
    const rdEl = document.getElementById('b_return_date');
    if (rdEl) rdEl.scrollIntoView({behavior:'smooth', block:'center'});
    return;
  }

  // ── Password validation when creating an account ─────────
  if (accOpen) {
    if (!fields.password) {
      showFieldError('password', 'Please enter a password.');
      toast('Please enter a password to create your account.', 'error');
      return;
    }
    if (fields.password.length < 8) {
      showFieldError('password', 'Password must be at least 8 characters.');
      toast('Password must be at least 8 characters long.', 'error');
      return;
    }
    if (fields.password !== fields.password_confirm) {
      showFieldError('password_confirm', 'Passwords do not match.');
      toast('Your passwords do not match. Please retype them.', 'error');
      return;
    }
  }

  // Require Terms & Conditions + Cancellation Policy acceptance
  if (!fields.terms_accepted) {
    const errEl = document.getElementById('err_terms_accepted');
    if (errEl) errEl.textContent = 'Please accept the Terms & Conditions and Cancellation Policy to continue.';
    const wrap = document.getElementById('termsCheckboxWrap');
    if (wrap) {
      wrap.classList.add('terms-error');
      wrap.scrollIntoView({behavior:'smooth', block:'center'});
    }
    hasError = true;
  }
  if (hasError) return;

  const btn = $id('btnNext');
  btn.disabled = true; btn.textContent = '⏳ Processing…';

  // If we already have a pending booking from this session and the form
  // hasn't materially changed, skip the POST and just re-show step 2.
  if (pendingBooking && pendingBooking.reference) {
    const sigNow  = `${fields.vehicle}|${fields.pickup_date}|${fields.return_date}|${fields.email}|${fields.with_driver}|${fields.baby_seat}`;
    const sigPrev = pendingBooking._sig || '';
    if (sigNow === sigPrev) {
      // Same booking, same details — re-display order summary and advance
      populateOrderSummary(pendingBooking);
      currentStep = 2; updateStepUI();
      btn.disabled = false; btn.textContent = 'Continue →';
      return;
    }
    // Form CHANGED — tell the server to UPDATE the existing booking
    // (instead of creating a duplicate). edit_ref auth-checks via email match.
    fields.edit_ref = pendingBooking.reference;
  }

  try {
    const data = await postJSON('/booking/submit/', fields);
    if (data.ok) {
      // Stamp signature so a re-submit with same fields is a no-op
      data._sig = `${fields.vehicle}|${fields.pickup_date}|${fields.return_date}|${fields.email}|${fields.with_driver}|${fields.baby_seat}`;
      pendingBooking = data;
      // Persist the inputs + the resulting booking so a browser Back from
      // the payment page can restore the modal at Step 1 with the form
      // pre-filled AND pendingBooking set — meaning the next submit goes
      // through edit_ref and updates the booking rather than creating a
      // duplicate. Stored under a hire-type-aware key so each flow has
      // its own state.
      try {
        sessionStorage.setItem('munwan_pending_booking', JSON.stringify({
          fields: fields,       // user inputs (for repopulating Step 1)
          booking: data,        // server response (for resuming Step 2 / edit_ref)
          ts: Date.now(),
        }));
      } catch (_) {}
      // ── Corporate hire: skip payment step, show invoice confirmation ──
      // The server has already generated an invoice number, sent the email,
      // and returned invoice_number/url/pdf_url. We swap Step 3's content
      // to show the invoice success state instead of the normal "booking
      // confirmed" message, then advance to Step 3.
      if (data.is_invoiced) {
        showInvoiceConfirmation(data);
        currentStep = 3; updateStepUI();
      } else {
        populateOrderSummary(data);
        currentStep = 2; updateStepUI();
      }
      if (data.account_created) {
        applyLoggedInNav();
        toast('Account created! You\'re now signed in.', 'success');
      }
    } else {
      if (data.errors) {
        Object.entries(data.errors).forEach(([k,msgs]) => showFieldError(k, Array.isArray(msgs)?msgs[0]:String(msgs)));
        // Special-case: account email already taken — surface a prominent toast
        // with a Sign In suggestion, plus scroll the email field into view.
        if (data.account_email_taken || (data.errors.email && /already exists/i.test(String(data.errors.email)))) {
          toast('An account with this email already exists. Please sign in first, or untick "Create an account".', 'error');
          const emailEl = $id('b_email');
          if (emailEl) emailEl.scrollIntoView({behavior:'smooth', block:'center'});
        } else {
          // Generic field error — scroll the FIRST errored field into view
          // and show a toast so mobile users (who may have scrolled past
          // the error) understand what went wrong.
          const firstKey = Object.keys(data.errors)[0];
          const firstEl = $id('b_' + firstKey);
          if (firstEl) firstEl.scrollIntoView({behavior:'smooth', block:'center'});
          const firstMsg = data.errors[firstKey];
          const msg = Array.isArray(firstMsg) ? firstMsg[0] : String(firstMsg);
          toast(msg || 'Please fix the highlighted field.', 'error');
        }
      } else {
        toast(data.error || 'Booking failed. Please check all fields.', 'error');
      }
    }
  } catch (err) { toast(err.message, 'error'); }
  finally { btn.disabled=false; btn.textContent='Continue →'; }
}

// ── Populate summary — correctly adds driver fee ──────────
function populateOrderSummary(data) {
  const days = parseInt(data.days) || 1;
  // For airport transfer / safari bookings, the "× N days" makes no sense —
  // show the booking type and vehicle/service label instead.
  const isTransfer = !!(data.is_transfer || (pendingBooking && pendingBooking.is_transfer));
  const isSafari   = !!(data.is_safari   || (pendingBooking && pendingBooking.is_safari));
  if (isTransfer) {
    setText('sum_vehicle_days', `✈️ Airport Transfer · ${data.vehicle}`);
  } else if (isSafari) {
    setText('sum_vehicle_days', `🦁 Safari Package · ${data.vehicle} · ${days} day${days!==1?'s':''}`);
  } else {
    setText('sum_vehicle_days', `${data.vehicle} × ${days} day${days!==1?'s':''}`);
  }
  setText('sum_base', `$${parseFloat(data.base_price).toFixed(2)}`);

  const dRow = $id('sum_driver_row');
  const driverFee = parseFloat(data.driver_fee) || 0;
  if (data.with_driver && driverFee > 0) {
    if (dRow) dRow.style.display = '';
    setText('sum_driver', `$${driverFee.toFixed(2)}`);
  } else {
    if (dRow) dRow.style.display = 'none';
  }

  // Baby seat row
  const bRow = $id('sum_baby_row');
  const babyFee = parseFloat(data.baby_seat_fee) || 0;
  if (data.baby_seat && babyFee > 0) {
    if (bRow) bRow.style.display = '';
    setText('sum_baby', `$${babyFee.toFixed(2)}`);
  } else {
    if (bRow) bRow.style.display = 'none';
  }

  setText('sum_total', `$${parseFloat(data.total_usd).toFixed(2)}`);
  setText('sum_kes', `≈ KES ${parseFloat(data.total_kes).toLocaleString()}`);

  // Update M-Pesa display
  setText('mpesa_amount_disp', `KES ${parseFloat(data.total_kes).toLocaleString()}`);
}

// ── Payment tab selection ─────────────────────────────────
// Only one payment method now (Paystack — handles Card/M-Pesa/Apple Pay
// inside its popup). This function is kept as a near-no-op so any cached
// HTML or call site doesn't break; it just ensures the Paystack panel is
// visible and the Continue button hidden (Paystack has its own button).
function selectPayTab(tab) {
  currentPayTab = 'paystack';
  const pp = $id('panel_paystack');
  if (pp) pp.style.display = '';
  const meth = $id('current_pay_method');
  if (meth) meth.value = 'paystack_card';
  // Paystack has its own inline "Pay Securely" button — the modal's
  // Continue button is redundant on Step 2.
  const payBtn = $id('btnNext');
  if (payBtn) payBtn.style.display = 'none';
}

// ── Paystack sub-tabs (legacy, no longer in DOM) ──────────
// Kept as a no-op so any cached HTML calling this doesn't error.
function selectFwSub(sub) { /* removed; Paystack popup handles channel selection */ }

// ── Mark checkout-in-progress so reminder cron skips this booking ─────
// Fire-and-forget; we don't want to block the customer's payment flow if
// this lightweight POST fails (the worst case is they get a reminder email
// they didn't strictly need).
function markPaymentAttempt() {
  try {
    const csrf = document.querySelector('meta[name="csrf-token"]');
    fetch('/payments/attempt/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrf ? csrf.content : '',
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      credentials: 'same-origin',
    }).catch(() => { /* ignore — non-critical */ });
  } catch (_) { /* ignore */ }
}

// ── Paystack inline popup ─────────────────────────────────
// Paystack Inline reference: https://paystack.com/docs/payments/accept-payments/
function triggerPaystackCard() {
  markPaymentAttempt();  // record checkout-in-progress
  let pk = ($id('paystackPk')||{}).value || '';
  pk = pk.trim();  // strip any whitespace from .env that crept in

  // Diagnostics — log to console so we can debug "Please enter a valid Key"
  // errors from the Paystack popup. Common causes: secret key (sk_*) instead
  // of public key (pk_*), trailing whitespace, or empty .env value.
  console.log('[Paystack] key prefix:', pk.slice(0, 8) || '(empty)');
  if (pk && !pk.startsWith('pk_')) {
    console.error('[Paystack] Public key must start with "pk_test_" or "pk_live_". Got:', pk.slice(0, 12));
    toast('Paystack key misconfigured (must start with pk_). Tell support.', 'error');
    return;
  }

  if (!pk || pk.includes('REPLACE_ME') || !window.PaystackPop) {
    // Dev/test mode — simulate success so you can test the confirmation flow
    toast('Demo mode: simulating successful payment (Paystack keys not configured).', 'info');
    finalisePayment('paystack', {
      paystack_ref: 'PS-TEST-' + Date.now(),
      payment_method: 'paystack',
    });
    return;
  }

  const booking = pendingBooking;
  // Paystack expects amount in the smallest unit of the currency
  // For KES, that's "kobo" = amount × 100
  const amountKobo = Math.round(parseFloat(booking.total_kes || 0) * 100);

  if (!amountKobo || amountKobo <= 0) {
    console.error('[Paystack] Invalid amount:', booking.total_kes, '→ kobo:', amountKobo);
    toast('Could not start payment — booking total is 0. Please go back and re-enter the booking.', 'error');
    return;
  }

    // Paystack requires a UNIQUE ref per transaction attempt. If we re-use
    // booking.reference, the second click hits "Duplicate Transaction
    // Reference". So we append a short timestamp suffix per attempt. The
    // ORIGINAL booking.reference is carried in metadata so the webhook can
    // still match the payment back to the correct booking.
    const paystackRef = `${booking.reference}-${Date.now().toString(36).slice(-6)}`;

  const handler = PaystackPop.setup({
    key:       pk,
    email:     ($id('b_email')||{}).value || '',
    amount:    amountKobo,
    currency:  'KES',
    ref:       paystackRef,
    // What channels the popup exposes. "bank_transfer" & "ussd" are optional.
    channels:  ['card', 'bank', 'ussd', 'mobile_money', 'bank_transfer'],
    metadata: {
      booking_ref: booking.reference,
      vehicle:     booking.vehicle,
      days:        booking.days,
      custom_fields: [
        { display_name: 'Booking Ref', variable_name: 'booking_ref', value: booking.reference },
        { display_name: 'Vehicle',     variable_name: 'vehicle',     value: booking.vehicle   },
      ],
    },
    firstname: ($id('b_first_name')||{}).value || '',
    lastname:  ($id('b_last_name')||{}).value  || '',
    callback: function(response) {
      // response.reference is the transaction reference we verify server-side
      finalisePayment('paystack', {
        paystack_ref:   response.reference,
        payment_method: 'paystack',
      });
    },
    onClose: function() {
      // User dismissed the popup without paying — do nothing
    },
  });

  handler.openIframe();
}

// ── M-Pesa STK push ───────────────────────────────────────
// REMOVED — Daraja direct integration retired in favour of Paystack's
// unified payment popup, which handles M-Pesa, card, bank transfer,
// and USSD inside a single "Pay Securely" button.
// The historical /payments/mpesa/callback/ URL is still wired up so
// any old in-flight callbacks get logged, but new bookings flow
// through Paystack only.

// ── Step 1 — AIRPORT TRANSFER variant ──────────────────────
async function submitStep1Transfer() {
  clearErrors();
  const fields = {
    first_name:               val('b_first_name'),
    last_name:                val('b_last_name'),
    email:                    val('b_email'),
    phone:                    val('b_phone'),
    nationality:              val('b_nationality'),
    hire_type:                'transfer',
    transfer_direction:       val('b_transfer_direction') || 'FROM',
    transfer_car_type:        val('b_transfer_car_type'),
    transfer_location:        val('b_transfer_location'),
    transfer_destination_text: val('b_transfer_destination_text'),
    transfer_pickup_date:     val('b_transfer_pickup_date'),
    transfer_pickup_time:     val('b_transfer_pickup_time'),
    create_account:           accOpen ? 'on' : '',
    password:                 val('b_password'),
    password_confirm:         val('b_password2'),
    terms_accepted:           val('b_terms_accepted') ? 'on' : '',
    edit_ref:                 (pendingBooking && pendingBooking.reference) || '',
    website:                  val('b_website') || '',
    form_started_at:          val('b_form_started_at') || '',
  };
  let hasError = false;

  ['first_name','last_name','email','phone',
   'transfer_direction','transfer_car_type','transfer_location',
   'transfer_pickup_date','transfer_pickup_time'].forEach(f => {
    if (!fields[f] || !fields[f].toString().trim()) {
      showFieldError(f, 'This field is required.'); hasError = true;
    }
  });

  if (fields.email && fields.email.trim()) {
    const e = fields.email.trim();
    if (!e.includes('@') || e.indexOf('@') === e.length - 1 || !e.includes('.')) {
      showFieldError('email', 'Please enter a valid email address (must contain @ and a . — e.g. you@example.com).');
      hasError = true;
    }
  }

  if (hasError) return;

  // ── Edit-instead-of-duplicate ───────────────────────────
  // If we already have a pending transfer booking AND nothing has
  // materially changed, just re-display step 2 — don't POST again.
  // If something changed, attach edit_ref so server UPDATES the existing
  // booking instead of creating a duplicate.
  const sigNow  = `transfer|${fields.transfer_direction}|${fields.transfer_car_type}|${fields.transfer_location}|${fields.transfer_pickup_date}|${fields.transfer_pickup_time}|${fields.email}`;
  if (pendingBooking && pendingBooking.reference && pendingBooking.is_transfer) {
    const sigPrev = pendingBooking._sig || '';
    if (sigNow === sigPrev) {
      // Identical booking — just re-display the summary card
      populateOrderSummary({
        vehicle:    pendingBooking.vehicle_name || 'Airport Transfer',
        days:       1,
        base_price: pendingBooking.total_usd,
        total_usd:  pendingBooking.total_usd,
        total_kes:  pendingBooking.total_kes,
        total_eur:  pendingBooking.total_eur,
        driver_fee: '0', with_driver: false, baby_seat: false, baby_seat_fee: '0',
      });
      currentStep = 2; updateStepUI();
      return;
    }
    // Booking changed — update the existing one
    fields.edit_ref = pendingBooking.reference;
  }

  // Submit
  const btn = $id('btnNext');
  if (btn) { btn.disabled = true; btn.textContent = 'Booking…'; }
  try {
    const result = await postJSON('/booking/submit/', fields);
    if (!result.ok) {
      Object.entries(result.errors || {}).forEach(([k,v]) => showFieldError(k, v));
      toast(result.errors && Object.keys(result.errors).length === 1
        ? Object.values(result.errors)[0]
        : 'Please fix the errors and try again.', 'error');
      return;
    }
    pendingBooking = result;
    pendingBooking.is_transfer = true;
    pendingBooking._sig = sigNow;
    // Persist for back-nav (same logic as rental flow — see submitStep1)
    try {
      sessionStorage.setItem('munwan_pending_booking', JSON.stringify({
        fields: fields,
        booking: pendingBooking,
        ts: Date.now(),
      }));
    } catch (_) {}
    // Map transfer response into the shape populateOrderSummary expects.
    // This populates the standard "Your Booking" card on Step 2 so the
    // payment total isn't $0. We deliberately do NOT add a second
    // "transfer summary" card here — one summary is enough.
    populateOrderSummary({
      vehicle:       result.vehicle_name || 'Airport Transfer',
      days:          1,
      base_price:    result.total_usd,
      total_usd:     result.total_usd,
      total_kes:     result.total_kes,
      total_eur:     result.total_eur,
      driver_fee:    '0',
      with_driver:   false,
      baby_seat:     false,
      baby_seat_fee: '0',
    });
    currentStep = 2;
    updateStepUI();
    if (typeof renderPaymentTabs === 'function') renderPaymentTabs();
  } catch (err) {
    toast('Network error. Please try again.', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Next →'; }
  }
}

// ── Step 1 — SAFARI PACKAGE variant ─────────────────────────
async function submitStep1Safari() {
  clearErrors();

  // Validate destinations + days before sending
  if (!safariSelected.length) {
    showFieldError('safari_destinations', 'Pick at least one safari destination.');
    return;
  }

  const fields = {
    first_name:               val('b_first_name'),
    last_name:                val('b_last_name'),
    email:                    val('b_email'),
    phone:                    val('b_phone'),
    nationality:              val('b_nationality'),
    hire_type:                'safari',
    vehicle:                  val('b_safari_vehicle'),
    safari_destinations:      safariSelected.join(','),
    pickup_date:              val('b_safari_pickup_date'),
    pickup_time:              val('b_safari_pickup_time'),
    pickup_location:          val('b_safari_pickup_location'),
    hotel_address:            val('b_safari_hotel'),
    create_account:           accOpen ? 'on' : '',
    password:                 val('b_password'),
    password_confirm:         val('b_password2'),
    terms_accepted:           val('b_terms_accepted') ? 'on' : '',
    edit_ref:                 (pendingBooking && pendingBooking.reference) || '',
    website:                  val('b_website') || '',
    form_started_at:          val('b_form_started_at') || '',
  };
  // Per-destination day overrides
  Object.entries(safariDays).forEach(([id, days]) => {
    fields[`days_${id}`] = days;
  });

  let hasError = false;
  ['first_name','last_name','email','phone','vehicle',
   'pickup_date','pickup_time'].forEach(f => {
    const key = f === 'vehicle' ? 'vehicle' : f;
    if (!fields[key] || !String(fields[key]).trim()) {
      showFieldError(f === 'vehicle' ? 'safari_vehicle' : ('safari_' + f), 'This field is required.');
      hasError = true;
    }
  });
  if (fields.email && fields.email.trim()) {
    const e = fields.email.trim();
    if (!e.includes('@') || e.indexOf('@') === e.length - 1 || !e.includes('.')) {
      showFieldError('email', 'Please enter a valid email address.');
      hasError = true;
    }
  }
  if (hasError) return;

  // Edit-vs-create signature (mirrors transfer flow)
  const sigNow = `safari|${fields.vehicle}|${fields.safari_destinations}|${JSON.stringify(safariDays)}|${fields.pickup_date}|${fields.email}`;
  if (pendingBooking && pendingBooking.reference && pendingBooking.is_safari) {
    if ((pendingBooking._sig || '') === sigNow) {
      populateOrderSummary({
        vehicle:    pendingBooking.vehicle_name,
        days:       pendingBooking.total_days,
        base_price: pendingBooking.total_usd,
        total_usd:  pendingBooking.total_usd,
        total_kes:  pendingBooking.total_kes,
        total_eur:  pendingBooking.total_eur,
        driver_fee: '0', with_driver: true, baby_seat: false, baby_seat_fee: '0',
        is_safari:  true,
      });
      currentStep = 2; updateStepUI();
      return;
    }
    fields.edit_ref = pendingBooking.reference;
  }

  const btn = $id('btnNext');
  if (btn) { btn.disabled = true; btn.textContent = 'Booking…'; }
  try {
    const result = await postJSON('/booking/submit/', fields);
    if (!result.ok) {
      Object.entries(result.errors || {}).forEach(([k,v]) => {
        // Map server field names back to form input IDs where they differ
        const formField = ({
          vehicle:             'safari_vehicle',
          safari_destinations: 'safari_destinations',
          pickup_date:         'safari_pickup_date',
          pickup_time:         'safari_pickup_time',
        })[k] || k;
        showFieldError(formField, v);
      });
      toast('Please fix the errors and try again.', 'error');
      return;
    }
    pendingBooking = result;
    pendingBooking.is_safari = true;
    pendingBooking._sig = sigNow;
    // Persist for back-nav (same logic as rental flow)
    try {
      sessionStorage.setItem('munwan_pending_booking', JSON.stringify({
        fields: fields,
        booking: pendingBooking,
        ts: Date.now(),
      }));
    } catch (_) {}
    populateOrderSummary({
      vehicle:    result.vehicle_name,
      days:       result.total_days,
      base_price: result.total_usd,
      total_usd:  result.total_usd,
      total_kes:  result.total_kes,
      total_eur:  result.total_eur,
      driver_fee: '0', with_driver: true, baby_seat: false, baby_seat_fee: '0',
      is_safari:  true,
    });
    currentStep = 2;
    updateStepUI();
    if (typeof renderPaymentTabs === 'function') renderPaymentTabs();
  } catch (err) {
    toast('Network error. Please try again.', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Next →'; }
  }
}

// Render a "Booking Summary" block on Step 2 for airport transfer bookings.
// Stage 3 will polish this into a proper card matching the rental summary.
function renderTransferSummary(r) {
  const wrap = $id('paymentSummary') || $id('s2_summary') || $id('modalBody');
  if (!wrap) return;
  const summary = `
    <div style="background:rgba(21,101,255,.06);border:1px solid rgba(21,101,255,.2);
                padding:14px 16px;border-radius:10px;margin-bottom:14px;">
      <div style="font-weight:700;font-size:.95rem;margin-bottom:6px">
        ✈️ Airport Transfer · ${r.zone_label} · ${r.car_type_label}
      </div>
      <div style="font-size:.85rem;color:var(--muted);margin-bottom:4px">
        Vehicle: <strong>${r.vehicle_name}</strong>
        ${r.night_surcharge ? '· 🌙 Night surcharge applied' : ''}
      </div>
      <div style="font-size:1.05rem;font-weight:700;color:var(--blue-dark)">
        Total: KES ${r.total_kes.toLocaleString()} (≈ $${r.total_usd.toFixed(2)} · €${r.total_eur.toFixed(2)})
      </div>
      <div style="font-size:.78rem;color:var(--muted);margin-top:6px">
        Reference: ${r.reference}
      </div>
    </div>
  `;
  // Render to top of payment-step body (idempotent)
  const existing = document.getElementById('transferSummaryBlock');
  if (existing) existing.remove();
  const div = document.createElement('div');
  div.id = 'transferSummaryBlock';
  div.innerHTML = summary;
  wrap.insertBefore(div, wrap.firstChild);
}


// ── Step 2: submit payment ────────────────────────────────
// All Paystack-handled methods (card, M-Pesa, bank, USSD) go through
// triggerPaystackCard() — the popup itself lets the customer choose.
async function submitPayment() {
  // Only Paystack remains — its popup handles Card / M-Pesa / Apple Pay.
  triggerPaystackCard();
}

// ── Corporate hire: invoice confirmation (skips payment step) ─────
// Swaps the standard "Booking Confirmed" Step-3 content for an
// invoice-specific message + download/view buttons. The server has
// already generated the invoice, sent the email, and stored the PDF URL.
function showInvoiceConfirmation(data) {
  setText('confirmIcon', '📄');
  setText('confirmTitle', 'Invoice Sent!');
  setText('confirmSub',
    `An invoice has been emailed to you. Pay by ${data.invoice_due || 'pickup date'}.`);
  // The customer's PRIMARY identifier is the booking reference (DK-...).
  // Invoice number is a billing label only. Show both so they don't get
  // confused — the ref pill highlights the booking ref, and the smaller
  // line below shows the invoice number.
  setText('confirmRef', 'Booking: ' + (data.reference || '—'));
  const confirmWrap = document.querySelector('#fs3 .confirm-wrap');
  if (confirmWrap) {
    // Remove any previously-injected invoice metadata block (idempotent)
    const prev = document.getElementById('invoiceActions');
    if (prev) prev.remove();
    const prevMeta = document.getElementById('invoiceMeta');
    if (prevMeta) prevMeta.remove();

    // Smaller line showing the invoice number, for clarity
    const meta = document.createElement('div');
    meta.id = 'invoiceMeta';
    meta.style.cssText = 'font-size:.8rem;color:var(--muted);margin:-6px 0 14px;letter-spacing:.04em';
    meta.textContent = 'Invoice number: ' + (data.invoice_number || data.reference);
    confirmWrap.appendChild(meta);

    const actions = document.createElement('div');
    actions.id = 'invoiceActions';
    actions.style.cssText = 'display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin:18px 0 8px';
    actions.innerHTML =
      (data.invoice_pdf_url
        ? `<a href="${data.invoice_pdf_url}" class="inv-btn inv-btn-secondary" target="_blank" rel="noopener">⬇ Download PDF</a>`
        : '') +
      (data.invoice_url
        ? `<a href="${data.invoice_url}" class="inv-btn inv-btn-secondary" target="_blank" rel="noopener">📄 View Online</a>`
        : '') +
      `<a href="/?resume=${encodeURIComponent(data.reference)}" class="inv-btn inv-btn-primary">💳 Pay Invoice</a>`;
    confirmWrap.appendChild(actions);
  }
  // Hide step bar's "Payment" middle dot — it doesn't apply here
  const s2 = document.getElementById('s2');
  if (s2) s2.style.display = 'none';
}

// ── Payment error message translator ──────────────────────
// Backend can sometimes surface raw gateway error strings — these are
// useful in logs but bewildering to customers. This function takes whatever
// the server returned and produces a clear, actionable message.
// Falls back to a generic-but-friendly default if nothing matches.
function humanisePaymentError(raw, method) {
  // No message at all → very common for network drops + buggy gateway responses
  if (!raw || typeof raw !== 'string') {
    return 'Payment couldn\'t be completed. No response from the payment service — please check your internet connection and try again.';
  }
  const msg = String(raw).trim();
  const lower = msg.toLowerCase();

  // The "(status: none)" pattern that prompted this fix: gateway returned
  // an unexpected payload missing the status field. Most often this is a
  // dropped/timeout transaction — not actually a card decline.
  if (lower.includes('status: none') || lower.includes('status:none') ||
      lower === 'none' || lower === '(status: none)') {
    return 'We couldn\'t confirm the payment with the bank. This usually means the transaction timed out — please try again, or use a different card or M-Pesa.';
  }

  // Common Paystack error patterns
  if (lower.includes('declined') || lower.includes('insufficient'))
    return 'Your card was declined. This is usually due to insufficient funds, an expired card, or a block from your bank. Try a different card or M-Pesa.';
  if (lower.includes('invalid card') || lower.includes('invalid_card'))
    return 'The card details look invalid. Please double-check the card number, expiry, and CVV.';
  if (lower.includes('3d') || lower.includes('authentication failed'))
    return 'Card authentication failed. Your bank rejected the verification step — please try again or use a different card.';
  if (lower.includes('timeout') || lower.includes('timed out'))
    return 'The payment service timed out. Your card was not charged — please try again.';
  if (lower.includes('not found') || lower.includes('invalid reference'))
    return 'We couldn\'t match your payment to the booking. Please try again, or WhatsApp us if the issue continues.';
  if (lower.includes('cancelled') || lower.includes('canceled') || lower.includes('abandoned'))
    return 'The payment was cancelled before it completed. You can try again whenever you\'re ready.';
  if (lower.includes('amount') && lower.includes('mismatch'))
    return 'There was an amount mismatch with the gateway. Please refresh and try again, or contact support.';

  // M-Pesa specific
  if (method === 'mpesa') {
    if (lower.includes('request') && lower.includes('timeout'))
      return 'M-Pesa didn\'t respond in time. Check your phone — you might still get the prompt — or try again in a moment.';
    if (lower.includes('subscriber'))
      return 'M-Pesa says this number isn\'t reachable right now. Make sure your phone is on and the number is correct.';
    if (lower.includes('insufficient'))
      return 'Your M-Pesa balance is too low for this payment. Top up and try again.';
  }

  // Network errors (these come from postJSON when fetch itself fails)
  if (lower.includes('network') || lower.includes('failed to fetch'))
    return 'Network issue — your payment may or may not have gone through. Wait a minute, then check your booking under "Check Booking" before retrying.';
  if (lower.includes('server error'))
    return 'Our payment server hit an error. Your card was not charged. Please try again, or WhatsApp us at +254 727 745 907 if it keeps failing.';

  // Last resort: return the raw message if it's already human-readable.
  // We strip anything that looks like a developer string (codes, lower-case-only).
  if (msg.length > 80 || /^[a-z_]+$/.test(msg)) {
    return 'Payment couldn\'t be completed. Please try again, or use a different payment method. If the problem continues, WhatsApp us at +254 727 745 907.';
  }
  return msg;
}

// ── Finalise payment (common) ─────────────────────────────
async function finalisePayment(method, extra) {
  try {
    const data = { payment_method: method, ...extra };
    const res  = await postJSON('/payments/process/', data);
    if (res.ok) {
      setText('confirmRef', 'Ref: '+(res.reference||'—'));
      if (res.async) {
        setText('confirmIcon','📱'); setText('confirmTitle','Check Your Phone');
        setText('confirmSub','An STK push has been sent. Enter your M-Pesa PIN to complete payment.');
      } else {
        setText('confirmIcon','🎉'); setText('confirmTitle','Booking Confirmed!');
        setText('confirmSub','Your vehicle is reserved. A confirmation email has been sent.');
      }
      // Payment succeeded — remove the pending-booking flag so a future
      // back-nav doesn't restore a paid booking's data into the form.
      try { sessionStorage.removeItem('munwan_pending_booking'); } catch (_) {}
      currentStep=3; updateStepUI();
    } else {
      // Translate gateway/server error into a customer-readable message.
      // res.error can be a string, null, or an obscure technical message.
      const err = humanisePaymentError(res.error, method);
      if (method==='mpesa') setText('err_mpesa', err); else toast(err, 'error');
    }
  } catch (err) {
    // err.message is what postJSON throws (network/timeouts)
    const friendly = humanisePaymentError(err.message, method);
    toast(friendly, 'error');
  }
}

// ── Check Booking ─────────────────────────────────────────
function openCheckModal() {
  const o=$id('checkOverlay'); if(o) o.classList.add('open');
  document.body.style.overflow='hidden';
  const inp=$id('checkRefInput'); if(inp){inp.value='';setTimeout(()=>inp.focus(),100);}
  setHTML('checkResult','');
}
function closeCheckModal() {
  const o=$id('checkOverlay'); if(o) o.classList.remove('open');
  document.body.style.overflow='';
}
async function doCheckBooking() {
  const ref=val('checkRefInput').trim().toUpperCase(); if(!ref) return;
  setHTML('checkResult','<p style="color:var(--muted);font-size:.84rem;padding:10px 0">Looking up…</p>');
  try {
    const res=await fetch(`/booking/check/?reference=${encodeURIComponent(ref)}`,{headers:{'X-Requested-With':'XMLHttpRequest'}});
    const data=await res.json();
    if (data.ok) {
      // Build "Complete Payment" CTA only when booking is unpaid
      const isUnpaid = (data.payment || '').toLowerCase().includes('unpaid');
      const payBtn = isUnpaid
        ? `<a href="/?resume=${encodeURIComponent(data.reference)}#booking"
              style="display:block;margin-top:14px;padding:13px 18px;background:linear-gradient(135deg,#1565FF,#0B47C2);color:#fff;text-align:center;font-weight:700;border-radius:10px;text-decoration:none;font-size:.88rem;box-shadow:0 4px 12px rgba(21,101,255,.25)">
            💳 Complete Payment
           </a>`
        : '';
      setHTML('checkResult',
        `<div class="booking-result-card">
          <div style="font-size:1.8rem;margin-bottom:8px">✅</div>
          <div style="font-weight:800;margin-bottom:12px">Booking Found</div>
          <div class="result-row"><span class="rl">Reference</span><span class="rv">${data.reference}</span></div>
          <div class="result-row"><span class="rl">Vehicle</span><span class="rv">${data.vehicle}</span></div>
          <div class="result-row"><span class="rl">Pick-up</span><span class="rv">${data.pickup} · ${data.pickup_date}</span></div>
          <div class="result-row"><span class="rl">Return</span><span class="rv">${data.return_date}</span></div>
          <div class="result-row"><span class="rl">Status</span><span class="rv status-ok">${data.status}</span></div>
          <div class="result-row"><span class="rl">Payment</span><span class="rv">${data.payment}</span></div>
          <div class="result-row"><span class="rl">Total</span><span class="rv">$${data.total_usd}</span></div>
          ${payBtn}
        </div>`);
    } else {
      setHTML('checkResult',`<div class="check-error">❌ ${data.error||'No booking found.'}</div>`);
    }
  } catch(_){ setHTML('checkResult','<div class="check-error">❌ Network error. Please try again.</div>'); }
}

// ── Terms & Conditions checkbox helper ──────────────────
function clearTermsError() {
  const errEl = document.getElementById('err_terms_accepted');
  const wrap  = document.getElementById('termsCheckboxWrap');
  if (errEl) errEl.textContent = '';
  if (wrap)  wrap.classList.remove('terms-error');
}