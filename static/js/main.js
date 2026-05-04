'use strict';

// ── Globals ──────────────────────────────────────────────
let currentStep    = 1;
let pendingBooking = null;
let accOpen        = false;
let currentPayTab  = 'paystack';
let currentFwSub   = 'card';
let VEHICLES       = [];

// ── Boot ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  try {
    const el = document.getElementById('vehicleData');
    if (el) VEHICLES = JSON.parse(el.textContent || '[]');
  } catch (e) { VEHICLES = []; }

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

  // hire-type tabs open booking modal
  document.querySelectorAll('#hireTabs .tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('#hireTabs .tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      openBookingModal();
      const sel = document.getElementById('b_hire_type');
      if (sel) {
        sel.value = tab.dataset.type || 'normal';
        if (typeof onHireTypeChange === 'function') onHireTypeChange();
        else updatePricingPreview();
      }
    });
  });

  ['b_pickup_date','b_return_date','b_with_driver','b_driver_option'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', updatePricingPreview);
  });
  // b_hire_type uses onHireTypeChange directly (set as inline onchange in template)

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

  // ── Resume unpaid booking from dashboard ─────────────
  try {
    const params = new URLSearchParams(window.location.search);
    const resumeRef = params.get('resume');
    if (resumeRef) {
      // Fetch the pending booking summary & jump straight to payment step
      // Pass the reference so this works for guest checkouts (no session cookie needed).
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
            };
            populateOrderSummary(pendingBooking);
            openBookingModal();
            currentStep = 2;
            updateStepUI();
            // Clean URL so refresh doesn't re-trigger
            window.history.replaceState({}, '', window.location.pathname);
          }
        })
        .catch(() => {});
    }

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
  } catch (e) { throw new Error('Network error. Please check your connection.'); }
  let json;
  try { json = await response.json(); }
  catch (_) { throw new Error('Server error (' + response.status + '). Please try again.'); }
  return json;
}

// ── DOM helpers ───────────────────────────────────────────
function $id(id) { return document.getElementById(id); }
function val(id) { const e=$id(id); if(!e) return ''; return e.type==='checkbox' ? e.checked : e.value; }
function setText(id, t) { const e=$id(id); if(e) e.textContent=String(t); }
function setHTML(id, h) { const e=$id(id); if(e) e.innerHTML=h; }
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
  // Defeat browser autofill on password fields (Chrome ignores autocomplete=off,
  // but actively clearing fields after modal opens always works)
  ['b_password','b_password2'].forEach(id => { const el=$id(id); if(el) el.value=''; });
  const today = new Date().toISOString().split('T')[0];
  [$id('b_pickup_date'), $id('b_return_date')].forEach(el => { if (el) el.min = today; });
  // Stamp form open time for bot time-trap (real humans take > 3s to fill)
  const ts = $id('b_form_started_at');
  if (ts && !ts.value) ts.value = String(Date.now());
}

function openBookingModalPrefilled() {
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
  // If modal isn't on this page, redirect home with type pre-selected
  if (!$id('bookingOverlay')) {
    window.location.href = '/?book=1&type=' + encodeURIComponent(type) + '#booking';
    return;
  }
  openBookingModal();
  const sel = $id('b_hire_type');
  if (sel) { sel.value = type; updatePricingPreview(); }
}

function closeBookingModal() {
  const overlay = $id('bookingOverlay'); if (overlay) overlay.classList.remove('open');
  document.body.style.overflow = '';
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

// ── Hire type changed — apply Safari Package vehicle filter ───────
// Safari Package may only be hired with safari-ready vehicles.
// We hide all non-safari options when 'safari' is picked, and restore
// them when any other hire type is picked. If the currently-selected
// vehicle is not safari-ready and the user picks Safari, clear it.
function onHireTypeChange() {
  const hire = val('b_hire_type');
  const veh  = $id('b_vehicle');
  if (!veh) { updatePricingPreview(); return; }

  const wantSafariOnly = (hire === 'safari');
  let clearedSelection = false;

  Array.from(veh.options).forEach(opt => {
    if (!opt.value) { opt.hidden = false; return; }   // keep "— Select Vehicle —"
    const cat = opt.dataset.category || '';
    const isSafari = (cat === 'safari');
    opt.hidden = wantSafariOnly && !isSafari;
    if (opt.selected && opt.hidden) {
      veh.value = '';                                  // unselect hidden choice
      clearedSelection = true;
    }
  });

  if (clearedSelection) {
    const errEl = $id('err_vehicle');
    if (errEl) errEl.textContent = 'Safari Package requires a Safari-Ready vehicle. Please pick one from the list.';
  } else {
    const errEl = $id('err_vehicle');
    if (errEl) errEl.textContent = '';
  }
  updatePricingPreview();
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
  let days = Math.ceil((new Date(rDate) - new Date(pDate)) / 86400000);
  if (isNaN(days) || days < 1) days = 1;
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

  // Scroll modal body to top when changing step — so user sees the start
  // of the new step (payment summary, not the buttons at the bottom)
  setTimeout(() => {
    const body = document.querySelector('.modal-body');
    if (body) body.scrollTop = 0;
  }, 0);
}

function nextStep() { if (currentStep===1) submitStep1(); }
function prevStep()  { if (currentStep>1) { currentStep--; updateStepUI(); } }

// ── Step 1 ────────────────────────────────────────────────
async function submitStep1() {
  clearErrors();
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
    create_account:  accOpen ? 'on' : '',
    password:        val('b_password'),
    password_confirm:val('b_password2'),
    terms_accepted:  val('b_terms_accepted') ? 'on' : '',
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

  // ── Minimum 2-day rental duration ────────────────────────
  // Compute days between pickup and return; reject if < 2.
  if (fields.pickup_date && fields.return_date) {
    const pd = new Date(fields.pickup_date + 'T' + (fields.pickup_time || '08:00'));
    const rd = new Date(fields.return_date + 'T' + (fields.return_time || '08:00'));
    const ms = rd - pd;
    const days = Math.ceil(ms / (1000 * 60 * 60 * 24));
    if (days < 2) {
      toast('Minimum rental is 2 days. Please adjust your return date.', 'error');
      showFieldError('return_date', 'Minimum rental period is 2 days.');
      const rdEl = document.getElementById('b_return_date');
      if (rdEl) rdEl.scrollIntoView({behavior:'smooth', block:'center'});
      return;
    }
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
      populateOrderSummary(data);
      currentStep = 2; updateStepUI();
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
  setText('sum_vehicle_days', `${data.vehicle} × ${days} day${days!==1?'s':''}`);
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
function selectPayTab(tab) {
  currentPayTab = tab;
  ['paystack','paypal'].forEach(t => {
    const pt=$id('ptab_'+t), pp=$id('panel_'+t);
    if (pt) pt.classList.toggle('active', t===tab);
    if (pp) pp.style.display = t===tab ? '' : 'none';
  });
  if (tab==='paypal') initPayPal();
}

// ── Paystack sub-tabs (card vs mpesa) ─────────────────────
function selectFwSub(sub) {
  currentFwSub = sub;
  ['card','mpesa'].forEach(s => {
    const btn=$id('fw_tab_'+s);
    if (btn) btn.classList.toggle('active', s===sub);
  });
  const cardPanel=$id('fw_card_panel'), mpesaPanel=$id('fw_mpesa_panel');
  if (cardPanel)  cardPanel.style.display  = sub==='card'  ? '' : 'none';
  if (mpesaPanel) mpesaPanel.style.display = sub==='mpesa' ? '' : 'none';
  const methInput=$id('current_pay_method');
  if (methInput) methInput.value = sub==='card' ? 'paystack_card' : 'paystack_mpesa';
}

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
  const pk = ($id('paystackPk')||{}).value || '';
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

  const handler = PaystackPop.setup({
    key:       pk,
    email:     ($id('b_email')||{}).value || '',
    amount:    amountKobo,
    currency:  'KES',
    ref:       booking.reference,
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
async function triggerMpesaPayment() {
  const phone = val('mpesa_phone').trim();
  if (!phone) { setText('err_mpesa','Phone number required.'); return; }
  markPaymentAttempt();  // record checkout-in-progress
  const btn = $id('mpesaPayBtn');
  btn.disabled=true; btn.textContent='⏳ Sending push…';
  try {
    await finalisePayment('mpesa', { mpesa_phone: phone, payment_method: 'mpesa' });
  } finally { btn.disabled=false; btn.textContent='📱 Send STK Push to My Phone'; }
}

// ── PayPal ────────────────────────────────────────────────
let paypalInited = false;
function initPayPal() {
  if (paypalInited) return;
  const clientId = ($id('paypalClientId')||{}).value || '';
  if (!clientId || clientId.includes('REPLACE_ME')) {
    const c=$id('paypal-button-container');
    if (c) c.innerHTML='<p style="color:var(--muted);font-size:.82rem;padding:10px 0">PayPal not configured yet. Add PAYPAL_CLIENT_ID to .env</p>';
    return;
  }
  if (!window.paypal) {
    const s=document.createElement('script');
    s.src=`https://www.paypal.com/sdk/js?client-id=${clientId}&currency=USD`;
    s.onload=renderPayPalButton;
    document.head.appendChild(s);
  } else { renderPayPalButton(); }
  paypalInited = true;
}
function renderPayPalButton() {
  const c=$id('paypal-button-container'); if (!c||!window.paypal) return;
  c.innerHTML='';
  paypal.Buttons({
    createOrder: async () => { markPaymentAttempt(); const r=await postJSON('/payments/paypal/create/',{}); if(r.ok) return r.orderID; throw new Error(r.error||'PayPal error'); },
    onApprove:  async (data) => { await finalisePayment('paypal',{paypal_order_id:data.orderID,payment_method:'paypal'}); },
    onError: err => toast('PayPal error: ' + err, 'error'),
  }).render('#paypal-button-container');
}

// ── Step 2: submit payment ────────────────────────────────
async function submitPayment() {
  const method = ($id('current_pay_method')||{}).value || 'paystack_card';
  if (method === 'paystack_card') { triggerPaystackCard(); return; }
  if (method === 'paystack_mpesa') { await triggerMpesaPayment(); return; }
  // PayPal handled by its own button — nothing to do here
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
      currentStep=3; updateStepUI();
    } else {
      const err=res.error||'Payment failed. Please try again.';
      if (method==='mpesa') setText('err_mpesa', err); else toast(err, 'error');
    }
  } catch (err) { toast(err.message || 'Payment error. Please try again.', 'error'); }
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