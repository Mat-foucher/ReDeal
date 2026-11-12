'use strict';
/* ReDeal frontend — dependency-free. Talks to the FastAPI backend.
   Motion: every transition is a spring (Apple response / damping-ratio form),
   interruptible at any frame because position and velocity are carried over. */

// Served by the backend → same origin. Served from :3000 (legacy dev port) → backend on :8000.
const API = location.port === '3000' ? `${location.protocol}//${location.hostname}:8000` : '';

async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(API + path, {
      method: opts.method || 'GET',
      headers: { ...(opts.body ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    const e = new Error('Can’t reach the ReDeal server. Is the backend running?');
    e.status = 0;
    throw e;
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === 'string' ? d
      : Array.isArray(d) ? d.map(x => `${(x.loc || []).slice(1).join('.')}: ${x.msg}`).join('; ')
      : `Request failed (${res.status})`;
    const e = new Error(msg);
    e.status = res.status;
    throw e;
  }
  return data;
}

/* ---------- Springs ---------- */
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const SPRING = {
  press:   { response: 0.16, damping: 1.0 },   // finger down: instant, no overshoot
  release: { response: 0.32, damping: 0.62 },  // finger up: small bounce
  tab:     { response: 0.35, damping: 0.82 },
  view:    { response: 0.30, damping: 1.0 },
  cardBack:{ response: 0.45, damping: 0.72 },  // snap back to center
  cardFly: { response: 0.55, damping: 0.95 },  // throw off-screen
  sheet:   { response: 0.42, damping: 0.86 },
  sheetOut:{ response: 0.36, damping: 1.0 },
  toast:   { response: 0.40, damping: 0.78 },
  seg:     { response: 0.30, damping: 0.80 },
};
const active = new Set();
let raf = 0, lastT = 0;
function frame(now) {
  const dt = Math.min(0.064, (now - lastT) / 1000) || 0.016;
  lastT = now;
  for (const s of [...active]) {
    const moving = s.step(dt);
    if (s.on) s.on(s.v);
    if (!moving && active.delete(s) && s.onRest) s.onRest();
  }
  raf = active.size ? requestAnimationFrame(frame) : 0;
}
class Spring {
  constructor(value = 0, eps = 0.01) { this.v = value; this.t = value; this.vel = 0; this.eps = eps; this.cfg(SPRING.tab); }
  cfg({ response, damping }) {
    // Apple form → stiffness/damping at mass 1: k = (2π/response)², c = 4π·ζ/response
    const r = reduceMotion.matches ? Math.min(response, 0.22) : response;
    const z = reduceMotion.matches ? 1 : damping;
    this.k = (2 * Math.PI / r) ** 2;
    this.c = 4 * Math.PI * z / r;
  }
  to(target, cfg, vel) {
    if (cfg) this.cfg(cfg);
    if (vel != null) this.vel = vel;
    this.t = target;
    active.add(this);
    if (!raf) { lastT = performance.now(); raf = requestAnimationFrame(frame); }
    return this;
  }
  set(value) { this.v = value; this.t = value; this.vel = 0; active.delete(this); if (this.on) this.on(value); }
  stop() { this.t = this.v; this.vel = 0; active.delete(this); }
  step(dt) {
    const n = Math.max(1, Math.ceil(dt / 0.004)), hh = dt / n;
    for (let i = 0; i < n; i++) {
      this.vel += (-this.k * (this.v - this.t) - this.c * this.vel) * hh;
      this.v += this.vel * hh;
    }
    if (Math.abs(this.v - this.t) < this.eps && Math.abs(this.vel) < this.eps * 20) { this.v = this.t; this.vel = 0; return false; }
    return true;
  }
}
/* Velocity tracker for gestures (px/s), smoothed over recent samples. */
function tracker() {
  let lx = 0, ly = 0, lt = 0, vx = 0, vy = 0;
  return {
    start(x, y) { lx = x; ly = y; lt = performance.now(); vx = vy = 0; },
    move(x, y) {
      const now = performance.now(), dt = Math.max(1, now - lt) / 1000;
      vx = 0.6 * (x - lx) / dt + 0.4 * vx; vy = 0.6 * (y - ly) / dt + 0.4 * vy;
      lx = x; ly = y; lt = now;
    },
    end() { return performance.now() - lt > 90 ? { vx: 0, vy: 0 } : { vx, vy }; },
  };
}
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/* Press feedback on pointer-down for every .press element. */
const pressSprings = new WeakMap();
function pressSpring(el) {
  let s = pressSprings.get(el);
  if (!s) { s = new Spring(1, 0.001); s.on = v => { el.style.scale = v === 1 ? '' : v; }; pressSprings.set(el, s); }
  return s;
}
let pressed = null;
document.addEventListener('pointerdown', e => {
  const el = e.target.closest && e.target.closest('.press');
  if (!el || el.disabled) return;
  pressed = el;
  pressSpring(el).to(el.classList.contains('row') ? 0.985 : 0.94, SPRING.press);
}, true);
function releasePress() { if (pressed) { pressSpring(pressed).to(1, SPRING.release); pressed = null; } }
document.addEventListener('pointerup', releasePress, true);
document.addEventListener('pointercancel', releasePress, true);
document.addEventListener('dragstart', releasePress, true);

/* ---------- DOM helpers ---------- */
const $ = sel => document.querySelector(sel);
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (typeof v !== 'string' && k in el) el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid);
  return el;
}
const ICONS = {
  card: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 10h18"/>',
  pile: '<rect x="6" y="3" width="12" height="16" rx="3"/><path d="M9 22h6"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16v4M17 18h4"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  chev: '<path d="M9 6l6 6-6 6"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 6.3"/><path d="M20 5v6h-6"/>',
};
function icon(name, size = 22, weight = 2) {
  return h('span', { class: 'icon', 'aria-hidden': 'true', html: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${weight}" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>` });
}
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const money = cents => usd.format((cents || 0) / 100);
const moneyShort = cents => (cents % 100 === 0 ? usd.format(cents / 100).replace(/\.00$/, '') : usd.format(cents / 100));
function parseMoney(str, emptyValue = null) {
  const s = String(str).replace(/[$,\s]/g, '');
  if (s === '') return emptyValue;
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null;
  return Math.round(parseFloat(s) * 100);
}
const MONO_COLORS = ['#1B7F3B', '#0062CC', '#B4460F', '#8A3FB5', '#B3174F', '#4A4A52'];
function mono(name, lg) {
  let hash = 0;
  for (const ch of String(name)) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  const el = h('div', { class: 'mono' + (lg ? ' lg' : ''), 'aria-hidden': 'true' }, (String(name).trim()[0] || '?').toUpperCase());
  el.style.background = MONO_COLORS[hash % MONO_COLORS.length];
  return el;
}
function safeLink(url, text, cls) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
    return h('a', { href: u.href, target: '_blank', rel: 'noopener noreferrer', class: cls }, text || u.hostname.replace(/^www\./, ''));
  } catch { return null; }
}
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const fmtDate = iso => { const d = new Date(iso); return isNaN(d) ? '—' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); };
let uid = 0;

function head(eyebrow, title, trailing) {
  return h('header', { class: 'head' },
    h('div', null, h('div', { class: 'eyebrow' }, eyebrow), h('h1', { class: 't-large' }, title)),
    trailing);
}
function section(title, ...kids) {
  return h('section', { class: 'section' }, title && h('h2', { class: 'section-title' }, title), kids);
}
const foot = text => h('p', { class: 'section-foot' }, text);
function infoRow(label, value) {
  return h('div', { class: 'row wrap' }, h('span', { class: 'grow' }, h('span', null, label)), h('span', { class: 'trail num' }, value));
}
function emptyState(iconName, title, text, button) {
  return h('div', { class: 'empty' },
    h('div', { class: 'glyph' }, icon(iconName, 32)),
    h('h2', { class: 't-title2' }, title),
    h('p', { class: 't-sub dim' }, text),
    button);
}
function segmented(options, value, onChange, label) {
  let index = Math.max(0, options.findIndex(o => o.value === value));
  const thumb = h('div', { class: 'seg-thumb' });
  const sp = new Spring(index, 0.001);
  sp.on = v => { thumb.style.transform = `translateX(${v * 100}%)`; };
  const btns = options.map((o, i) => h('button', {
    type: 'button', class: 'seg-btn', 'aria-pressed': String(i === index),
    onpointerdown: () => sp.to(i + (index - i) * 0.12, SPRING.press), // lean toward the touched segment immediately
    onpointerleave: () => sp.to(index, SPRING.seg),
    onclick: () => {
      btns[index].setAttribute('aria-pressed', 'false');
      index = i;
      btns[i].setAttribute('aria-pressed', 'true');
      sp.to(i, SPRING.seg);
      onChange(o.value);
    },
  }, o.label));
  const root = h('div', { class: 'segmented', role: 'group', 'aria-label': label }, thumb, btns);
  root.style.setProperty('--n', options.length);
  sp.on(index);
  return root;
}
function field(label, attrs, wide) {
  const id = 'f' + (++uid);
  const input = h('input', { id, class: 'input', autocomplete: 'off', ...attrs });
  return { input, row: h('div', { class: 'row field' + (wide ? ' wide' : '') }, h('label', { for: id }, label), input) };
}
const moneyField = (label, placeholder = '$0.00') => field(label, { type: 'text', inputmode: 'decimal', placeholder, class: 'input right' }, true);

/* ---------- Toasts ---------- */
function toast(message, kind = '') {
  const el = h('div', { class: 'toast ' + kind, role: 'status' }, h('span', { class: 'dot' }), h('span', null, message));
  $('#toasts').append(el);
  const y = new Spring(-90);
  let leaving = false;
  y.on = v => { el.style.transform = `translate3d(0,${v}px,0)`; el.style.opacity = clamp(1 + v / 60, 0, 1); };
  y.onRest = () => { if (leaving) el.remove(); };
  y.on(-90);
  y.to(0, SPRING.toast);
  setTimeout(() => { leaving = true; y.to(-90, SPRING.sheetOut); }, 3800);
}

/* ---------- Sheets ---------- */
const sheets = [];
function setInert(on) { for (const id of ['#main', '#tabs']) $(id).inert = on; }
function openSheet({ title, action, build, onClose }) {
  const id = 'sheet' + (++uid);
  const backdrop = h('div', { class: 'backdrop' });
  const body = h('div', { class: 'sheet-body' });
  const actionBtn = action && h('button', { type: 'button', class: 'nav-btn strong press', onclick: () => action.run(ctl) }, action.label);
  const headEl = h('div', { class: 'sheet-head' },
    h('div', { class: 'grabber' }),
    h('div', { class: 'sheet-bar' },
      h('button', { type: 'button', class: 'nav-btn press', onclick: () => ctl.close() }, action ? 'Cancel' : 'Done'),
      h('h2', { id }, title),
      actionBtn || h('span')));
  const sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': id }, headEl, body);
  const host = h('div', { class: 'sheet-host' }, backdrop, sheet);
  const prevFocus = document.activeElement;
  const travel = () => window.innerHeight;
  let closing = false, closed = false, result;
  const y = new Spring(travel(), 0.05);
  y.on = v => {
    sheet.style.transform = `translate3d(0,${v < 0 ? v * 0.18 : v}px,0)`; // rubber-band above rest
    backdrop.style.opacity = clamp(1 - v / (sheet.offsetHeight || travel()), 0, 1);
    if (closing && v >= travel() - 1) finish();
  };
  function finish() {
    if (closed) return;
    closed = true;
    y.stop();
    host.remove();
    sheets.splice(sheets.indexOf(ctl), 1);
    if (sheets.length) sheets[sheets.length - 1].host.inert = false; else setInert(false);
    if (prevFocus && prevFocus.isConnected) prevFocus.focus({ preventScroll: true });
    if (onClose) onClose(result);
  }
  const ctl = {
    host, body,
    close(value, vel) { result = value; closing = true; y.to(travel() + 60, SPRING.sheetOut, vel); },
    busy(on) { if (actionBtn) actionBtn.disabled = on; body.querySelectorAll('button.btn').forEach(b => { b.disabled = on; }); },
  };
  // Drag the header to dismiss; grabbing mid-flight cancels a close in progress.
  const tr = tracker();
  let drag = null;
  headEl.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('button')) return;
    closing = false;
    y.stop();
    drag = { start: e.clientY - y.v };
    tr.start(e.clientX, e.clientY);
    headEl.setPointerCapture(e.pointerId);
  });
  headEl.addEventListener('pointermove', e => {
    if (!drag) return;
    tr.move(e.clientX, e.clientY);
    y.set(e.clientY - drag.start);
  });
  const endDrag = () => {
    if (!drag) return;
    drag = null;
    const { vy } = tr.end();
    if (y.v + vy * 0.2 > sheet.offsetHeight * 0.4) ctl.close(undefined, vy);
    else y.to(0, SPRING.sheet, vy);
  };
  headEl.addEventListener('pointerup', endDrag);
  headEl.addEventListener('pointercancel', endDrag);
  backdrop.addEventListener('click', () => ctl.close());

  body.append(...[].concat(build(ctl)).flat(Infinity).filter(Boolean));
  if (sheets.length) sheets[sheets.length - 1].host.inert = true;
  setInert(true);
  sheets.push(ctl);
  document.body.append(host);
  y.on(y.v);
  y.to(0, SPRING.sheet);
  if (matchMedia('(pointer: fine)').matches) {
    const first = body.querySelector('input, button');
    if (first) first.focus({ preventScroll: true });
  }
  return ctl;
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && sheets.length) sheets[sheets.length - 1].close();
});
function confirmSheet({ title, message, confirm, green, danger }) {
  return new Promise(resolve => {
    openSheet({
      title,
      onClose: v => resolve(v === true),
      build: ctl => [
        h('p', { class: 't-sub dim sheet-msg' }, message),
        h('button', { type: 'button', class: 'btn block press' + (green ? ' green-fill' : '') + (danger ? ' red-fill' : ''), onclick: () => ctl.close(true) }, confirm),
      ],
    });
  });
}

/* ---------- State ---------- */
const S = { subs: [], pile: [], history: [], switches: [], scanning: false, scan: null, loaded: false, offline: null, pp: null, scout: null, scoutBusy: false, filter: 'all' };
const subById = id => S.subs.find(s => s.id === id);
// Monthly saving of a simulated switch, in cents (0 if the plan was never switched).
const switchSaving = s => (s.switch ? s.switch.original_monthly_cost_cents - s.monthly_cost_cents : 0);
// "replaces Netflix Standard": names the provider when we can tell which plan the deal was priced against.
function replacesText(d) {
  if (d.current_provider) return `replaces ${d.current_provider} ${d.current_plan}`;
  const sub = subById(d.subscription_id);
  let provider = '';
  if (sub && sub.switch && sub.switch.original_plan_name === d.current_plan) provider = sub.switch.original_provider;
  else if (sub && sub.plan_name === d.current_plan) provider = sub.provider;
  return `replaces ${provider ? provider + ' ' : ''}${d.current_plan}`;
}

async function loadSubs() { S.subs = await api('/subscriptions'); renderSubs(); }
async function loadPile() { S.pile = (await api('/agent/pile')).deals; renderPile(); renderSubs(); updateBadge(); }
async function loadHistory() {
  const [hist, sw] = await Promise.all([api('/agent/history'), api('/switch-requests')]);
  S.history = hist.deals; S.switches = sw; renderActivity();
}
async function loadAll() {
  try {
    await Promise.all([loadSubs(), loadPile(), loadHistory()]);
    S.offline = null;
  } catch (e) { S.offline = e.message; }
  S.loaded = true;
  renderAll();
}
function renderAll() { renderSubs(); renderPile(); renderActivity(); renderLabs(); updateBadge(); }

/* ---------- PayPal ---------- */
// After a PayPal switch, the buyer confirms on PayPal's own page. Opened from a tap so pop-up blockers allow it.
function paypalConfirmSheet(url, message) {
  openSheet({ title: 'Confirm in PayPal', build: ctl => [
    h('p', { class: 't-sub dim sheet-msg' }, message),
    h('a', { href: url, class: 'btn block press', rel: 'noopener', onclick: () => ctl.close() }, 'Continue to PayPal'),
    foot('PayPal sandbox. You sign in as your sandbox buyer and approve the new plan; PayPal then sends you back here.'),
  ] });
}
let linking = false;   // ignore extra taps while an import is in flight
async function linkPaypal() {
  if (linking) return;
  linking = true;
  setTimeout(() => { linking = false; }, 4000);
  try {
    const r = await api('/paypal/link-demo', { method: 'POST' });
    toast(r.created ? `${r.subscription.provider} added from PayPal` : `${r.subscription.provider} is already in your plans`, 'ok');
    await loadAll();
    go('subs');
  } catch (e) { toast(e.message, 'err'); }
}
// Replace everything with the sample set (three everyday plans plus the PayPal sandbox plan). Asks first if there's data to lose.
async function loadSample() {
  if (S.subs.length || S.history.length) {
    const ok = await confirmSheet({
      title: 'Reset to Sample Data',
      message: 'This deletes every subscription, deal and offer here and loads the sample set: Spotify, Netflix, YouTube Premium and the PayPal sandbox plan. Nothing changes with any real provider.',
      confirm: 'Reset', danger: true,
    });
    if (!ok) return;
  }
  try {
    const r = await api('/sample/load', { method: 'POST' });
    await loadAll();
    go('subs');
    if (r.approval_url) paypalConfirmSheet(r.approval_url, 'An earlier demo switched the PayPal plan to Saver. Confirm on PayPal to move it back to Standard, so the scan has a deal to find.');
    else toast(r.message, r.paypal === 'error' ? 'err' : 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// PayPal sends the buyer back with ?paypal=approved or ?paypal=cancelled; re-read what PayPal now bills.
async function handlePaypalReturn() {
  const p = new URLSearchParams(location.search).get('paypal');
  const hasLinked = S.subs.some(s => s.paypal_subscription_id);
  if (!p && !hasLinked) return;
  if (p) history.replaceState(null, '', location.pathname + location.hash);
  try {
    await api('/paypal/sync', { method: 'POST' });
    await Promise.all([loadSubs(), loadPile()]);
    if (p === 'approved') toast('PayPal confirmed the change. Your plan is updated.', 'ok');
    if (p === 'cancelled') toast('You cancelled in PayPal, so PayPal kept your old plan.');
  } catch (e) { if (p) toast(e.message, 'err'); }
}
function updateBadge() {
  const b = $('#pile-badge');
  b.hidden = !S.pile.length;
  b.textContent = S.pile.length;
  $('[data-tab="pile"]').setAttribute('aria-label', S.pile.length ? `Pile, ${plural(S.pile.length, 'deal')}` : 'Pile');
}
function offlineState() {
  return emptyState('refresh', 'Server unavailable', S.offline,
    h('button', { type: 'button', class: 'btn press', onclick: loadAll }, 'Try Again'));
}

/* ---------- Subscriptions ---------- */
function renderSubs() {
  const v = $('#view-subs');
  const addBtn = h('button', { type: 'button', class: 'icon-btn filled press', 'aria-label': 'Add subscription', onclick: openAddSub }, icon('plus', 22, 2.5));
  const kids = [head(S.loaded ? `${S.subs.filter(s => s.status === 'active').length} active` : 'Loading', 'Subscriptions', addBtn)];
  if (S.offline) kids.push(offlineState());
  else if (S.loaded && !S.subs.length) {
    kids.push(emptyState('card', 'No subscriptions yet', 'Add what you pay each month, or bring in a plan billed through PayPal, and ReDeal’s AI agent will find cheaper plans.',
      h('div', { class: 'btn-col' },
        h('button', { type: 'button', class: 'btn press', onclick: loadSample }, icon('sparkle', 20), 'Load Sample Data'),
        h('div', { class: 'btn-row' },
          h('button', { type: 'button', class: 'btn gray press', onclick: openAddSub }, 'Add Subscription'),
          h('button', { type: 'button', class: 'btn gray press', onclick: linkPaypal }, icon('link', 20), 'Add from PayPal')))));
  } else if (S.subs.length) {
    const monthly = S.subs.reduce((n, s) => n + s.monthly_cost_cents, 0);
    const saved = S.subs.reduce((n, s) => n + switchSaving(s), 0);
    kids.push(
      h('section', { class: 'surface' },
        h('div', null, h('div', { class: 't-foot dim', style: 'font-weight:600' }, 'Monthly spend'), h('div', { class: 'hero-num num' }, money(monthly)),
          saved > 0 && h('div', { class: 't-headline green num saved-line' }, `Saving ${money(saved * 12)} per year`, h('span', { class: 't-foot dim' }, ' · projected'))),
        h('div', { class: 'stats' },
          h('div', { class: 'stat' }, h('span', { class: 't-cap dim' }, 'Per year'), h('b', { class: 'num' }, money(monthly * 12))),
          h('button', { type: 'button', class: 'stat press', style: 'text-align:left', onclick: () => go('pile') },
            h('span', { class: 't-cap dim' }, 'Deals waiting'), h('b', { class: S.pile.length ? 'green' : '' }, S.pile.length ? `${S.pile.length} in pile` : 'None')))),
      section('Your plans',
        h('div', { class: 'group' }, S.subs.map(s =>
          h('button', { type: 'button', class: 'row has-mono press', onclick: () => openSubDetail(s) },
            mono(s.provider),
            h('span', { class: 'grow' }, h('span', { class: 't-headline' }, s.provider),
              h('span', { class: 't-sub dim' }, s.switch ? `${s.plan_name} · was ${s.switch.original_provider} ${s.switch.original_plan_name}` : `${s.plan_name} · ${s.paypal_subscription_id ? 'Billed via PayPal' : cap(s.category)}`)),
            h('span', { class: 'price-col' }, h('span', { class: 'num' }, money(s.monthly_cost_cents)),
              switchSaving(s) > 0 && h('span', { class: 't-foot green num' }, `saves ${money(switchSaving(s))}`)),
            h('span', { class: 'chev' }, icon('chev', 16, 2.5))))),
        !S.subs.some(s => s.paypal_subscription_id) && h('button', { type: 'button', class: 'btn sm gray press', onclick: linkPaypal }, icon('link', 18), 'Add a Plan Billed via PayPal'),
        foot('Plans billed via PayPal are switched through PayPal when you approve a deal. For other plans, ReDeal tracks the switch and you finish it on the provider’s site.')));
  }
  v.replaceChildren(...kids);
}

function openAddSub() { openSubForm(null); }
function openSubForm(existing) {
  const provider = field('Provider', { type: 'text', placeholder: 'Netflix', maxlength: 120, autocapitalize: 'words', value: existing && existing.provider });
  const plan = field('Plan', { type: 'text', placeholder: 'Standard', maxlength: 120, autocapitalize: 'words', value: existing && existing.plan_name });
  const price = moneyField('Monthly price');
  const fee = moneyField('Cancellation fee');
  if (existing) {
    price.input.value = (existing.monthly_cost_cents / 100).toFixed(2);
    if (existing.cancellation_fee_cents) fee.input.value = (existing.cancellation_fee_cents / 100).toFixed(2);
  }
  let category = existing ? existing.category : 'digital';
  const err = h('p', { class: 'form-error', role: 'alert' });
  async function submit(ctl) {
    const cents = parseMoney(price.input.value), feeCents = parseMoney(fee.input.value, 0);
    if (!provider.input.value.trim()) { err.textContent = 'Enter the provider name.'; provider.input.focus(); return; }
    if (!plan.input.value.trim()) { err.textContent = 'Enter the plan name.'; plan.input.focus(); return; }
    if (cents == null) { err.textContent = 'Enter the monthly price, like 15.99.'; price.input.focus(); return; }
    if (feeCents == null) { err.textContent = 'Enter the cancellation fee as an amount, or leave it empty.'; fee.input.focus(); return; }
    ctl.busy(true);
    const body = { provider: provider.input.value.trim(), plan_name: plan.input.value.trim(), category, monthly_cost_cents: cents, cancellation_fee_cents: feeCents };
    try {
      if (existing) {
        const sub = await api(`/subscriptions/${existing.id}`, { method: 'PUT', body });
        S.subs = S.subs.map(x => (x.id === sub.id ? sub : x));
        ctl.close();
        toast(`${sub.provider} updated`, 'ok');
        // A new price changes the savings on open cards (and may remove some), so refetch them.
        await Promise.all([loadPile(), loadHistory()]).catch(() => {});
        renderAll();
      } else {
        const sub = await api('/subscriptions', { method: 'POST', body });
        S.subs.unshift(sub);
        renderSubs(); renderPile();
        ctl.close();
        toast(`${sub.provider} added`, 'ok');
      }
    } catch (e) { err.textContent = e.message; ctl.busy(false); }
  }
  openSheet({
    title: existing ? 'Edit Subscription' : 'New Subscription',
    action: { label: existing ? 'Save' : 'Add', run: submit },
    build: ctl => h('form', { novalidate: true, onsubmit: e => { e.preventDefault(); submit(ctl); } },
      h('div', { class: 'group' }, provider.row, plan.row),
      section('Category', segmented(['digital', 'internet', 'mobile', 'utility', 'other'].map(c => ({ value: c, label: cap(c) })), category, c => { category = c; }, 'Category')),
      section(null, h('div', { class: 'group' }, price.row, fee.row), foot('Enter what you actually pay each month. The AI scout compares offers against this price.')),
      err,
      h('button', { type: 'submit', class: 'btn block press' }, existing ? 'Save Changes' : 'Add Subscription')),
  });
}
async function deleteSub(sub, detailCtl) {
  const deals = S.history.filter(d => d.subscription_id === sub.id).length;
  const ok = await confirmSheet({
    title: 'Delete Subscription',
    message: `This removes ${sub.provider} ${sub.plan_name}${deals ? ` and its ${plural(deals, 'deal')} from the pile and Activity` : ''}. It can’t be undone. Nothing changes with the provider.`,
    confirm: 'Delete', danger: true,
  });
  if (!ok) return;
  try {
    await api(`/subscriptions/${sub.id}`, { method: 'DELETE' });
    detailCtl.close();
    toast(`${sub.provider} deleted`);
    await loadAll();
  } catch (e) { toast(e.message, 'err'); }
}

function openSubDetail(sub) {
  let months = 12;
  const offersBox = h('div', { class: 'section' });
  async function refresh() {
    try {
      const [offers, switches] = await Promise.all([api(`/subscriptions/${sub.id}/offers`), api('/switch-requests')]);
      S.switches = switches;
      const evals = await Promise.all(offers.map(o => api(`/subscriptions/${sub.id}/offers/${o.id}/evaluate?months=${months}`)));
      renderOffers(offers, evals);
      renderActivity();
    } catch (e) { offersBox.replaceChildren(h('div', { class: 'inline-status' }, e.message)); }
  }
  function renderOffers(offers, evals) {
    if (!offers.length) { offersBox.replaceChildren(foot('No manual offers yet. Add one to compare it against this plan.')); return; }
    offersBox.replaceChildren(...offers.map((o, i) => {
      const ev = evals[i], req = S.switches.find(r => r.subscription_id === sub.id && r.offer_id === o.id);
      const saving = ev.estimated_savings_cents;
      const act = async (path, okMsg) => {
        try { await api(path, { method: 'POST' }); toast(okMsg, 'ok'); } catch (e) { toast(e.message, 'err'); }
        refresh();
      };
      return h('div', { class: 'item' },
        h('div', { class: 'item-head' }, mono(o.provider),
          h('div', { class: 'grow' }, h('span', { class: 't-headline' }, o.plan_name), h('span', { class: 't-sub dim' }, o.provider)),
          h('div', { class: 'trail' }, h('div', { class: 't-headline num ' + (saving > 0 ? 'green' : '') }, (saving >= 0 ? 'Save ' : 'Costs ') + money(Math.abs(saving))), h('div', { class: 't-foot dim' }, `over ${ev.horizon_months} mo`))),
        h('div', { class: 'stats' },
          h('div', { class: 'stat' }, h('span', { class: 't-cap dim' }, o.promotional_months ? `First ${o.promotional_months} mo` : 'Promo'), h('b', { class: 'num' }, o.promotional_months ? money(o.promotional_monthly_cents) : 'None')),
          h('div', { class: 'stat' }, h('span', { class: 't-cap dim' }, 'Then'), h('b', { class: 'num' }, money(o.regular_monthly_cents), h('small', null, ' /mo')))),
        h('p', { class: 't-foot dim' }, [o.activation_fee_cents ? `Activation fee ${money(o.activation_fee_cents)}. ` : '', o.eligibility_notes ? o.eligibility_notes + ' ' : '', ev.caveat].join('')),
        o.source_url && safeLink(o.source_url, null, 't-sub'),
        !req ? h('button', { type: 'button', class: 'btn sm gray press', onclick: () => act(`/subscriptions/${sub.id}/offers/${o.id}/request-switch`, 'Switch requested. Awaiting your approval.') }, 'Request Switch')
          : req.status === 'pending_approval' ? h('button', { type: 'button', class: 'btn sm press', onclick: () => act(`/switch-requests/${req.id}/approve`, 'Approved. No merchant action was performed.') }, 'Approve Switch')
          : h('span', { class: 'badge green' }, 'Approved · not executed'));
    }));
  }
  openSheet({
    title: sub.provider,
    build: ctl => [
      h('div', { class: 'item-head' }, mono(sub.provider, true),
        h('div', { class: 'grow' }, h('span', { class: 't-title2' }, sub.plan_name), h('span', { class: 't-sub dim' }, `${money(sub.monthly_cost_cents)} per month`))),
      h('div', { class: 'group' },
        infoRow('Category', cap(sub.category)),
        infoRow('Per year', money(sub.monthly_cost_cents * 12)),
        infoRow('Cancellation fee', money(sub.cancellation_fee_cents)),
        infoRow('Status', cap(sub.status))),
      sub.paypal_subscription_id && section('PayPal', h('div', { class: 'group' },
        infoRow('Billed via', 'PayPal (sandbox)'),
        infoRow('Subscription', sub.paypal_subscription_id))),
      sub.switch && section('Switched plan',
        h('div', { class: 'group' },
          infoRow('Switched from', `${sub.switch.original_provider} ${sub.switch.original_plan_name}`),
          infoRow('Was', `${money(sub.switch.original_monthly_cost_cents)} per month`),
          h('div', { class: 'row wrap' }, h('span', { class: 'grow' }, h('span', null, 'Saving')), h('span', { class: 'trail num green' }, `${money(switchSaving(sub) * 12)} per year`))),
        h('button', { type: 'button', class: 'btn block gray press', onclick: async () => {
          try {
            const back = await api(`/subscriptions/${sub.id}/undo-switch`, { method: 'POST' });
            S.subs = S.subs.map(x => (x.id === back.id ? back : x));
            ctl.close();
            toast(`Back to ${back.provider} ${back.plan_name}. The deal is in the pile again.`, 'ok');
            await Promise.all([loadPile(), loadHistory()]).catch(() => {});
            renderAll();
            if (back.paypal_approval_url) paypalConfirmSheet(back.paypal_approval_url, `PayPal is switching ${back.provider} back to ${back.plan_name}. Confirm it on PayPal to finish.`);
          } catch (e) { toast(e.message, 'err'); }
        } }, sub.switch.steps > 1 ? 'Undo Last Switch' : 'Undo Switch'),
        foot(sub.paypal_subscription_id ? 'Undo asks PayPal to switch back to the previous plan.' : 'ReDeal tracks this switch. If you already changed plans with the provider, undo it there too.')),
      section('Manual offers',
        segmented([6, 12, 24].map(m => ({ value: m, label: `${m} months` })), months, m => { months = m; refresh(); }, 'Comparison horizon'),
        offersBox),
      h('button', { type: 'button', class: 'btn block gray press', onclick: () => openAddOffer(sub, refresh) }, 'Add Offer'),
      h('div', { class: 'btn-row' },
        h('button', { type: 'button', class: 'btn gray press', onclick: () => { ctl.close(); openSubForm(sub); } }, 'Edit'),
        h('button', { type: 'button', class: 'btn gray danger press', onclick: () => deleteSub(sub, ctl) }, 'Delete')),
    ],
  });
  refresh();
}

function openAddOffer(sub, done) {
  const provider = field('Provider', { type: 'text', placeholder: sub.provider, maxlength: 120 });
  const plan = field('Plan', { type: 'text', placeholder: 'Plan name', maxlength: 120 });
  const promo = moneyField('Promo price / mo', 'Optional');
  const promoMonths = field('Promo months', { type: 'text', inputmode: 'numeric', placeholder: '0', class: 'input right' }, true);
  const regular = moneyField('Regular price / mo');
  const fee = moneyField('Activation fee');
  const notes = field('Eligibility', { type: 'text', placeholder: 'Optional notes' });
  const url = field('Source', { type: 'url', inputmode: 'url', placeholder: 'https://', autocapitalize: 'none' });
  const err = h('p', { class: 'form-error', role: 'alert' });
  async function submit(ctl) {
    const reg = parseMoney(regular.input.value), feeCents = parseMoney(fee.input.value, 0);
    const pm = promoMonths.input.value.trim() === '' ? 0 : Number(promoMonths.input.value);
    const promoCents = parseMoney(promo.input.value, reg);
    if (!provider.input.value.trim() || !plan.input.value.trim()) { err.textContent = 'Enter the provider and plan.'; return; }
    if (reg == null) { err.textContent = 'Enter the regular monthly price.'; regular.input.focus(); return; }
    if (promoCents == null || feeCents == null) { err.textContent = 'Amounts should look like 12.99.'; return; }
    if (!Number.isInteger(pm) || pm < 0 || pm > 120) { err.textContent = 'Promo months must be between 0 and 120.'; promoMonths.input.focus(); return; }
    ctl.busy(true);
    try {
      await api(`/subscriptions/${sub.id}/offers`, { method: 'POST', body: {
        provider: provider.input.value.trim(), plan_name: plan.input.value.trim(),
        promotional_monthly_cents: promoCents, promotional_months: pm, regular_monthly_cents: reg,
        activation_fee_cents: feeCents, eligibility_notes: notes.input.value.trim(), source_url: url.input.value.trim() || null } });
      ctl.close();
      toast('Offer added', 'ok');
      done();
    } catch (e) { err.textContent = e.message; ctl.busy(false); }
  }
  openSheet({
    title: 'New Offer',
    action: { label: 'Add', run: submit },
    build: ctl => h('form', { novalidate: true, onsubmit: e => { e.preventDefault(); submit(ctl); } },
      h('div', { class: 'group' }, provider.row, plan.row),
      h('div', { class: 'group' }, regular.row, promo.row, promoMonths.row, fee.row),
      h('div', { class: 'group' }, notes.row, url.row),
      err,
      h('button', { type: 'submit', class: 'btn block press' }, 'Add Offer')),
  });
}

/* ---------- Swipe pile ---------- */
let topCard = null;
function dealBadges(d) {
  const out = [];
  if (d.paypal_plan_id) out.push(h('span', { class: 'badge green' }, 'Switches via PayPal'));
  if (d.status === 'conditional') out.push(h('span', { class: 'badge orange' }, 'Conditional · check eligibility'));
  if (d.billing_period === 'yearly') out.push(h('span', { class: 'badge' }, `Billed yearly · ${money(d.upfront_cents)} upfront`));
  return out.length ? h('div', { class: 'badges' }, out) : null;
}
function priceTiles(d) {
  return h('div', { class: 'stats' },
    h('div', { class: 'stat big' }, h('span', { class: 't-cap dim' }, 'Now'), h('b', { class: 'num' }, money(d.current_monthly_cents), h('small', null, ' /mo'))),
    h('div', { class: 'stat big' }, h('span', { class: 't-cap dim' }, d.billing_period === 'yearly' ? 'Offer (avg)' : 'Offer'), h('b', { class: 'num' }, money(d.target_monthly_cents), h('small', null, ' /mo'))));
}
function buildCard(d) {
  return h('article', { class: 'card', 'aria-label': `${d.plan_name} from ${d.provider}, saves ${moneyShort(d.annual_savings_cents)} per year` },
    h('div', { class: 'stamp yes' }, icon('check', 26, 2.8)),
    h('div', { class: 'stamp no' }, icon('x', 26, 2.8)),
    h('div', { class: 'card-head' }, mono(d.provider, true),
      h('div', { class: 'grow' }, h('span', { class: 't-headline' }, d.plan_name), h('span', { class: 't-sub dim' }, `${d.provider} · ${replacesText(d)}`))),
    dealBadges(d),
    h('div', { class: 'save' }, h('span', { class: 't-foot dim', style: 'font-weight:600' }, 'Projected savings'),
      h('div', { class: 'save-line' }, h('span', { class: 'save-num num' }, moneyShort(d.annual_savings_cents)), h('span', { class: 'save-unit' }, 'per year'))),
    priceTiles(d),
    h('div', { class: 'card-text' },
      d.eligibility && h('div', null, h('span', { class: 't-foot dim', style: 'font-weight:600' }, 'Eligibility'), h('p', { class: 't-sub clamp' }, d.eligibility)),
      d.tradeoffs && h('div', null, h('span', { class: 't-foot dim', style: 'font-weight:600' }, 'Trade-offs'), h('p', { class: 't-sub clamp' }, d.tradeoffs))),
    h('div', { class: 'card-foot' },
      safeLink(d.source_url) || h('span'),
      h('button', { type: 'button', onclick: () => openDealDetail(d, true) }, 'Details')));
}
function renderPile() {
  const v = $('#view-pile');
  topCard = null;
  const scanBtn = h('button', { type: 'button', class: 'icon-btn press', 'aria-label': S.scanning ? 'Scan in progress' : 'Scan for deals with AI', disabled: S.scanning, onclick: startScan },
    S.scanning ? h('span', { class: 'spinner' }) : icon('sparkle'));
  const kids = [head(`${plural(S.pile.length, 'deal')} found by AI`, 'Swipe Pile', scanBtn)];
  if (S.scanning) kids.push(h('div', { class: 'inline-status', role: 'status' }, h('span', { class: 'spinner' }), h('span', { id: 'scan-status-text' }, scanText())));
  if (S.offline) kids.push(offlineState());
  else if (!S.pile.length) {
    kids.push(S.subs.length
      ? emptyState('pile', S.scanning ? 'Scanning…' : 'You’re all caught up', 'Scan and ReDeal’s AI agent looks for cheaper plans: in the merchant’s PayPal catalog for plans billed via PayPal, and on the web for the rest. Nothing changes until you approve.',
          !S.scanning && h('button', { type: 'button', class: 'btn press', onclick: startScan }, icon('sparkle', 20), 'Scan for Deals with AI'))
      : emptyState('pile', 'Nothing to scout yet', 'Add a subscription with its monthly price, then scan for deals.',
          h('button', { type: 'button', class: 'btn press', onclick: () => { go('subs'); openAddSub(); } }, 'Add Subscription')));
  } else {
    const deck = h('div', { class: 'deck', tabindex: '0', role: 'group', 'aria-roledescription': 'card stack', 'aria-label': 'Deal cards. Left arrow passes, right arrow approves.' });
    const cards = S.pile.slice(0, 4).map(buildCard);
    for (let i = cards.length - 1; i >= 0; i--) { if (i > 0) cards[i].inert = true; deck.append(cards[i]); }
    setupDeck(deck, cards, S.pile[0]);
    deck.addEventListener('keydown', e => {
      if (e.target !== deck) return;
      if (e.key === 'ArrowRight') { e.preventDefault(); flingTop(1); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); flingTop(-1); }
    });
    kids.push(deck, h('div', { class: 'actions' },
      h('button', { type: 'button', class: 'round press', 'aria-label': 'Pass', onclick: () => flingTop(-1) }, icon('x', 26, 2.6)),
      h('button', { type: 'button', class: 'round yes press', 'aria-label': 'Approve', onclick: () => flingTop(1) }, icon('check', 26, 2.6))));
  }
  v.replaceChildren(...kids);
}
function setupDeck(deck, cards, deal) {
  const el = cards[0];
  el.classList.add('top');
  const [yes, no] = el.querySelectorAll('.stamp');
  const sx = new Spring(0, 0.05), sy = new Spring(0, 0.05);
  const threshold = () => Math.min(140, (deck.clientWidth || 360) * 0.36);
  const exitX = () => window.innerWidth / 2 + deck.clientWidth / 2 + 60;
  const state = { pending: 0, done: false };
  function apply() {
    const x = sx.v, y = sy.v;
    const rot = reduceMotion.matches ? 0 : clamp(x * 0.045, -14, 14);
    el.style.transform = `translate3d(${x}px,${y}px,0) rotate(${rot}deg)`;
    const p = clamp(Math.abs(x) / threshold(), 0, 1);
    yes.style.opacity = x > 0 ? p : 0;
    no.style.opacity = x < 0 ? p : 0;
    yes.style.scale = no.style.scale = 0.6 + 0.4 * p;
    // Cards underneath rise as the top one leaves.
    for (let i = 1; i < cards.length; i++) {
      const d = i - p;
      cards[i].style.transform = `translate3d(0,${-d * 13}px,0) scale(${1 - d * 0.05})`;
      cards[i].style.opacity = clamp(3 - d, 0, 1); // only the deepest card fades; translucent cards would show text through
    }
    if (state.pending && !state.done && Math.abs(x) > exitX() - 20) {
      state.done = true;
      sx.stop(); sy.stop();
      commitSwipe(deal, state.pending > 0 ? 'approve' : 'pass');
    }
  }
  sx.on = apply; sy.on = apply;
  apply();
  function fling(dir, vx = 0, vy = 0) {
    state.pending = dir;
    const minV = 900 * dir;
    sx.to(exitX() * dir, SPRING.cardFly, dir > 0 ? Math.max(vx, minV) : Math.min(vx, minV));
    sy.to(sy.v + vy * 0.25, SPRING.cardFly, vy);
  }
  const tr = tracker();
  let drag = null;
  el.addEventListener('pointerdown', e => {
    if (e.button !== 0 || state.done || e.target.closest('a,button')) return;
    state.pending = 0;               // grabbing a card mid-flight takes it back
    sx.stop(); sy.stop();
    drag = { ox: e.clientX - sx.v, oy: e.clientY - sy.v, moved: false, sx0: e.clientX, sy0: e.clientY };
    tr.start(e.clientX, e.clientY);
    el.setPointerCapture(e.pointerId);
    el.classList.add('dragging');
  });
  el.addEventListener('pointermove', e => {
    if (!drag) return;
    tr.move(e.clientX, e.clientY);
    if (Math.hypot(e.clientX - drag.sx0, e.clientY - drag.sy0) > 6) drag.moved = true;
    sx.v = sx.t = e.clientX - drag.ox;
    sy.v = sy.t = e.clientY - drag.oy;
    apply();
  });
  const end = e => {
    if (!drag) return;
    const moved = drag.moved;
    drag = null;
    el.classList.remove('dragging');
    const { vx, vy } = tr.end();
    const projected = sx.v + vx * 0.18;   // where the throw would land
    if (e.type === 'pointerup' && Math.abs(projected) > threshold()) fling(Math.sign(projected), vx, vy);
    else {
      sx.to(0, SPRING.cardBack, vx); sy.to(0, SPRING.cardBack, vy);
      if (!moved && e.type === 'pointerup') openDealDetail(deal, true);
    }
  };
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
  topCard = { fling, state, isDragging: () => !!drag };
}
function flingTop(dir) {
  if (!topCard || topCard.state.done || topCard.isDragging()) return;
  if (topCard.state.pending === dir) return;
  topCard.fling(dir);
}
async function commitSwipe(deal, decision) {
  const hadFocus = document.activeElement && document.activeElement.closest('.deck, .actions');
  S.pile = S.pile.filter(d => d.id !== deal.id);
  renderPile(); renderSubs(); updateBadge();
  if (hadFocus) { const deck = $('.deck'); if (deck) deck.focus({ preventScroll: true }); }
  try {
    const r = await api(`/agent/pile/${deal.id}/swipe`, { method: 'POST', body: { decision } });
    if (r.approval_url) paypalConfirmSheet(r.approval_url, `ReDeal asked PayPal to move ${deal.provider} to ${deal.plan_name} (${money(deal.target_monthly_cents)}/mo). Confirm it on PayPal to finish.`);
    else toast(r.message, decision === 'approve' ? 'ok' : '');
    loadHistory().catch(() => {});
    // An approval switches the plan, which also re-prices the cards left in the pile.
    if (decision === 'approve') Promise.all([loadSubs(), loadPile()]).catch(() => {});
  } catch (e) {
    toast(e.message, 'err');
    loadPile().catch(() => {});
  }
}
function scanText() {
  const p = S.scan;
  const tail = ' You can leave this page; the scan keeps running.';
  if (!p || !p.total) return 'Starting the scan…' + tail;
  if (p.phase === 'paypal') return `Checking PayPal plan catalogs: ${p.done} of ${p.total} done.` + tail;
  if (p.phase === 'research') return `Researching offers: ${p.done} of ${plural(p.total, 'subscription')} done.` + tail;
  return `Reviewing offers: ${p.done} of ${p.total} checked.` + tail;
}
let scanTimer = 0;
// The scan runs on the server; this just follows its progress and picks up a scan already in flight after a reload.
async function pollScan() {
  clearTimeout(scanTimer);
  let st;
  try { st = await api('/agent/scan/status'); } catch { scanTimer = setTimeout(pollScan, 4000); return; }
  S.scan = st;
  if (st.running) {
    if (!S.scanning) { S.scanning = true; renderPile(); }
    const el = $('#scan-status-text');
    if (el) el.textContent = scanText();
    scanTimer = setTimeout(pollScan, 2000);
    return;
  }
  if (!S.scanning) return;
  S.scanning = false;
  await Promise.all([loadPile(), loadHistory()]).catch(() => {});
  renderPile();
  const r = st.result;
  if (r) {
    toast(`${plural(r.new_deals, 'new deal')} · ${r.rejected} rejected · ${r.skipped || 0} already seen`, 'ok');
    if (r.errors && r.errors.length) toast(r.errors[0], 'err');
  }
}
async function startScan() {
  if (S.scanning) return;
  if (!S.subs.length) { toast('Add a subscription first.'); return; }
  const ok = await confirmSheet({
    title: 'Scan for Deals with AI',
    message: `ReDeal’s agent checks ${plural(S.subs.filter(s => s.status === 'active').length, 'active subscription')}: plans billed via PayPal against the merchant’s PayPal catalog, the rest with OpenAI web search, then an AI review of each candidate. This uses your OpenAI API key and can take a minute or two.`,
    confirm: 'Start Scan',
  });
  if (!ok) return;
  try {
    S.scan = await api('/agent/scan', { method: 'POST' });
    S.scanning = true;
    renderPile();
    scanTimer = setTimeout(pollScan, 1500);
  } catch (e) {
    if (e.status === 409) pollScan(); else toast(e.message, 'err');
  }
}
const STATUS = { candidate: 'In pile', conditional: 'In pile · conditional', mock_approved: 'Approved', passed: 'Passed' };
const statusText = d => (d.status === 'mock_approved' ? (d.paypal_plan_id ? 'Approved · switched via PayPal' : 'Approved · finish with provider') : STATUS[d.status] || d.status);
function openDealDetail(d, canAct) {
  openSheet({
    title: 'Deal Details',
    build: ctl => [
      h('div', { class: 'item-head' }, mono(d.provider, true),
        h('div', { class: 'grow' }, h('span', { class: 't-title2' }, d.plan_name), h('span', { class: 't-sub dim' }, `${d.provider} · ${replacesText(d)}`))),
      dealBadges(d),
      h('div', { class: 'save' }, h('span', { class: 't-foot dim', style: 'font-weight:600' }, 'Projected savings'),
        h('div', { class: 'save-line' }, h('span', { class: 'save-num num' }, moneyShort(d.annual_savings_cents)), h('span', { class: 'save-unit' }, 'per year'))),
      priceTiles(d),
      d.eligibility && section('Eligibility', h('div', { class: 'group' }, h('p', { class: 'row t-sub' }, d.eligibility))),
      d.tradeoffs && section('Trade-offs', h('div', { class: 'group' }, h('p', { class: 'row t-sub' }, d.tradeoffs))),
      d.review_reason && section('AI review', h('div', { class: 'group' }, h('p', { class: 'row t-sub' }, d.review_reason))),
      h('div', { class: 'group' },
        infoRow('Status', statusText(d)),
        infoRow('Billing', cap(d.billing_period)),
        d.source_url && h('div', { class: 'row wrap' }, h('span', { class: 'grow' }, h('span', null, 'Source')), safeLink(d.source_url, null, 'trail'))),
      d.caveat && foot(d.caveat),
      canAct && h('div', { class: 'btn-row' },
        h('button', { type: 'button', class: 'btn gray press', onclick: () => { ctl.close(); flingTop(-1); } }, 'Pass'),
        h('button', { type: 'button', class: 'btn green-fill press', onclick: () => { ctl.close(); flingTop(1); } }, 'Approve')),
    ],
  });
}

/* ---------- Activity ---------- */
function renderActivity() {
  const v = $('#view-activity');
  const approved = S.history.filter(d => d.status === 'mock_approved');
  const projected = approved.reduce((n, d) => n + d.annual_savings_cents, 0);
  const groups = { all: () => true, approved: d => d.status === 'mock_approved', passed: d => d.status === 'passed', open: d => d.status === 'candidate' || d.status === 'conditional' };
  const list = S.history.filter(groups[S.filter]);
  const kids = [head(`${plural(S.history.length, 'deal')} reviewed by AI`, 'Activity')];
  if (S.offline) kids.push(offlineState());
  else {
    kids.push(
      h('section', { class: 'surface' },
        h('div', null, h('div', { class: 't-foot dim', style: 'font-weight:600' }, 'Projected from approvals'), h('div', { class: 'hero-num num green' }, moneyShort(projected), h('span', { class: 't-headline' }, ' per year'))),
        h('div', { class: 'stats' },
          h('div', { class: 'stat' }, h('span', { class: 't-cap dim' }, 'Approved'), h('b', { class: 'num' }, String(approved.length))),
          h('div', { class: 'stat' }, h('span', { class: 't-cap dim' }, 'Realized savings'), h('b', { class: 'num' }, money(0))))),
      activityFilter,
      list.length
        ? section(null, h('div', { class: 'group' }, list.map(d =>
            h('button', { type: 'button', class: 'row has-mono press', onclick: () => openDealDetail(d, false) },
              mono(d.provider),
              h('span', { class: 'grow' }, h('span', { class: 't-headline' }, d.plan_name), h('span', { class: 't-sub dim' }, statusText(d))),
              h('span', { class: 'num ' + (d.status === 'mock_approved' ? 'green' : 'dim') }, `${moneyShort(d.annual_savings_cents)}/yr`),
              h('span', { class: 'chev' }, icon('chev', 16, 2.5))))),
          foot('Savings are projected from approvals. Realized savings count only once a lower charge is verified, so they start at zero.'))
        : emptyState('clock', 'Nothing here yet', S.filter === 'all' ? 'Deals you approve or pass will appear here.' : 'No deals match this filter.'));
    if (S.switches.length) {
      kids.push(section('Manual switch requests', h('div', { class: 'group' }, S.switches.map(r => {
        const sub = subById(r.subscription_id);
        return h('div', { class: 'row' },
          h('span', { class: 'grow' }, h('span', { class: 't-headline' }, sub ? `${sub.provider} ${sub.plan_name}` : `Subscription ${r.subscription_id}`), h('span', { class: 't-sub dim' }, `Offer ${r.offer_id}`)),
          r.status === 'pending_approval'
            ? h('button', { type: 'button', class: 'btn sm press', onclick: async () => { try { await api(`/switch-requests/${r.id}/approve`, { method: 'POST' }); toast('Approved. No merchant action was performed.', 'ok'); } catch (e) { toast(e.message, 'err'); } loadHistory().catch(() => {}); } }, 'Approve')
            : h('span', { class: 'badge green' }, 'Approved · not executed'));
      }))));
    }
  }
  const focused = activityFilter.contains(document.activeElement) && document.activeElement;
  v.replaceChildren(...kids);
  if (focused) focused.focus({ preventScroll: true });
}
// Built once so its thumb spring and focus survive re-renders.
const activityFilter = segmented(
  [{ value: 'all', label: 'All' }, { value: 'approved', label: 'Approved' }, { value: 'passed', label: 'Passed' }, { value: 'open', label: 'In Pile' }],
  S.filter, f => { S.filter = f; renderActivity(); }, 'Filter');

/* ---------- Labs: demo data, PayPal sandbox tools, legacy web scout ---------- */
async function loadScout() {
  try { S.scout = await api('/scout/deals'); } catch (e) { S.scout = { deals: [], errors: [{ provider: 'Scout', reason: e.message }], scanned_at: null }; }
  renderLabs();
}
async function scanScout() {
  S.scoutBusy = true; renderLabs();
  try { S.scout = await api('/scout/scan', { method: 'POST' }); toast(`${plural(S.scout.deals.length, 'public price')} found`, 'ok'); }
  catch (e) { toast(e.message, 'err'); }
  S.scoutBusy = false; renderLabs();
}
async function scoutDecision(deal, decision) {
  try {
    const r = await api('/scout/mock-decision', { method: 'POST', body: { deal_id: deal.id, decision } });
    toast(r.message, decision === 'approve' ? 'ok' : '');
    if (decision === 'approve') deal._approved = true;
    else S.scout.deals = S.scout.deals.filter(d => d.id !== deal.id);
  } catch (e) { toast(e.message, 'err'); }
  renderLabs();
}
async function startSandboxSub(plan) {
  try {
    const r = await api('/paypal/subscriptions/create', { method: 'POST', body: { plan } });
    openSheet({ title: 'Sandbox Subscription', build: () => [
      h('div', { class: 'group' }, infoRow('Subscription', r.subscription_id || '—'), infoRow('Status', r.status || '—')),
      r.approval_url ? safeLink(r.approval_url, 'Continue in PayPal Sandbox', 'btn block') : foot('PayPal returned no approval link.'),
      foot('Approve as the sandbox buyer, then set this subscription ID in backend/.env to use it for the demo.'),
    ] });
  } catch (e) { toast(e.message, 'err'); }
}
function renderLabs() {
  const v = $('#view-labs');
  const kids = [head('PayPal sandbox tools', 'Labs')];
  kids.push(section('Demo data',
    h('button', { type: 'button', class: 'btn sm gray danger press', onclick: loadSample }, 'Reset to Sample Data'),
    foot('Starts over with Spotify, Netflix, YouTube Premium and the PayPal sandbox plan. If an earlier visitor switched the PayPal plan, you’ll be asked to confirm moving it back on PayPal.')));
  kids.push(section('Your PayPal plan',
    h('button', { type: 'button', class: 'btn sm press', onclick: linkPaypal }, icon('link', 18), 'Add Sandbox Subscription to Plans'),
    foot('Brings the subscription in PAYPAL_DEMO_SUBSCRIPTION_ID into Plans, priced from PayPal. Then scan in the Swipe Pile: the agent finds cheaper plans in the merchant’s PayPal catalog, and approving one switches it through PayPal.')));
  kids.push(section('Start a sandbox subscription',
    h('div', { class: 'btn-row' },
      h('button', { type: 'button', class: 'btn sm gray press', onclick: () => startSandboxSub('standard') }, 'Standard'),
      h('button', { type: 'button', class: 'btn sm gray press', onclick: () => startSandboxSub('saver') }, 'Saver')),
    foot('Creates a subscription in PayPal’s sandbox only. Requires sandbox credentials in backend/.env.')));
  // Legacy web scout
  const sc = S.scout, scKids = [
    h('button', { type: 'button', class: 'btn sm gray press', disabled: S.scoutBusy, onclick: scanScout }, S.scoutBusy ? h('span', { class: 'spinner' }) : null, S.scoutBusy ? 'Scanning…' : 'Scan Public Pricing Pages')];
  if (sc) {
    for (const d of sc.deals) {
      scKids.push(h('div', { class: 'item' },
        h('div', { class: 'item-head' }, mono(d.provider),
          h('div', { class: 'grow' }, h('span', { class: 't-headline' }, d.target_plan), h('span', { class: 't-sub dim' }, `${d.provider} · replaces ${d.current_plan}`)),
          h('div', { class: 'trail t-headline num green' }, `${moneyShort(d.estimated_annual_savings_cents)}/yr`)),
        priceTiles(d),
        h('p', { class: 't-foot dim' }, d.caveat),
        safeLink(d.source_url, null, 't-sub'),
        d._approved ? h('span', { class: 'badge green' }, 'Approved · simulation')
          : h('div', { class: 'btn-row' },
              h('button', { type: 'button', class: 'btn sm gray press', onclick: () => scoutDecision(d, 'pass') }, 'Pass'),
              h('button', { type: 'button', class: 'btn sm green-fill press', onclick: () => scoutDecision(d, 'approve') }, 'Approve'))));
    }
    if (sc.errors && sc.errors.length) scKids.push(h('div', { class: 'group' }, sc.errors.map(e => h('div', { class: 'row wrap' }, h('span', { class: 'grow' }, h('span', { class: 't-headline' }, e.provider), h('span', { class: 't-sub dim', style: 'white-space:normal' }, e.reason))))));
    scKids.push(foot(sc.scanned_at ? `Last scanned ${fmtDate(sc.scanned_at)}. Mock decisions reset when the server restarts.` : 'Not scanned yet. Reads explicit monthly prices from the pages in backend/scout_sources.json.'));
  }
  kids.push(section('Web scout (legacy)', scKids));
  v.replaceChildren(...kids);
}

/* ---------- Tabs ---------- */
const TABS = ['subs', 'pile', 'activity', 'labs'];
const tabSpring = new Spring(0, 0.001);
const track = $('.tab-track');
tabSpring.on = v => track.style.setProperty('--i', v);
const viewSpring = new Spring(1, 0.001);
let current = null;
function go(tab, instant) {
  if (!TABS.includes(tab)) tab = 'subs';
  if (tab === current) return;
  current = tab;
  for (const t of TABS) {
    $(`#view-${t}`).hidden = t !== tab;
    const btn = $(`[data-tab="${t}"]`);
    if (t === tab) btn.setAttribute('aria-current', 'page'); else btn.removeAttribute('aria-current');
  }
  const i = TABS.indexOf(tab), view = $(`#view-${tab}`);
  if (instant) tabSpring.set(i); else tabSpring.to(i, SPRING.tab);
  viewSpring.on = v => { view.style.opacity = v >= 1 ? '' : v; view.style.transform = v >= 1 ? '' : `translate3d(0,${(1 - v) * 10}px,0)`; };
  if (!instant) { viewSpring.set(0); viewSpring.to(1, SPRING.view); }
  window.scrollTo(0, 0);
  if (location.hash.slice(1) !== tab) history.replaceState(null, '', '#' + tab);
  if (tab === 'labs' && !S.scout) loadScout();
}
for (const btn of document.querySelectorAll('.tab')) {
  btn.querySelector('.tab-icon').replaceWith(icon(btn.querySelector('.tab-icon').dataset.icon));
  // Indicator starts moving on touch-down; the tab commits on click.
  btn.addEventListener('pointerdown', () => tabSpring.to(TABS.indexOf(btn.dataset.tab), SPRING.tab));
  btn.addEventListener('pointerleave', () => tabSpring.to(TABS.indexOf(current), SPRING.tab));
  btn.addEventListener('click', () => go(btn.dataset.tab));
}
window.addEventListener('hashchange', () => go(location.hash.slice(1)));

renderAll();
go(location.hash.slice(1) || 'subs', true);
loadAll().then(() => { pollScan(); handlePaypalReturn(); });
