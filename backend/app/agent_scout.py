"""AI research -> independent AI review -> deterministic savings -> persistent mock swipe pile.
No payment, cancellation or merchant-account operations are performed here.
"""
import asyncio
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .models import AuditEvent, ScoutDeal, SimulatedSwitch, Subscription

router = APIRouter(prefix='/agent', tags=['AI Deal Scout'])
scan_lock = asyncio.Lock()

RESEARCH = '''You research real, CURRENT US subscription offers via web search. For the supplied subscription, search official provider pages and credible retailer pages. Find at most 5 candidate plans, including competitors. Never invent a price, URL or active promotion. Return ONLY JSON {"candidates":[{"provider":"...","plan":"...","price":12.99,"billing_period":"monthly" or "yearly","source_url":"https://...","offer_type":"standard|student|family|bundle|promotion|competitor","eligibility":"...","tradeoffs":"...","evidence":"..."}]}. Price MUST be the total charge for one plan, never a per-person allocation. Yearly price must be the full annual payment. Omit unknown prices. Do not calculate savings.'''
VERIFY = '''Independently search the public web to review this candidate. Do not trust the researcher's claims. Check official provider pricing where possible, price and billing period, current availability, plan comparability, and eligibility. Return ONLY JSON {"price_supported":true/false,"billing_period_supported":true/false,"currently_available":true/false,"comparable":true/false,"source_url":"https://...","eligibility":"...","tradeoffs":"...","reason":"..."}. Use false when evidence is missing, dated, or ambiguous. Do not calculate savings. Never purchase anything.'''

# Strict schemas keep the working Colab web-search pipeline while ensuring
# the model returns parseable, predictable objects for the Swipe Pile.
def _string():
    return {'type': 'string'}

RESEARCH_SCHEMA = {
    'type': 'object',
    'properties': {
        'candidates': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'provider': _string(), 'plan': _string(),
                    'price': {'type': 'number'},
                    'billing_period': {'type': 'string', 'enum': ['monthly', 'yearly']},
                    'source_url': _string(),
                    'offer_type': {'type': 'string', 'enum': ['standard', 'student', 'family', 'bundle', 'promotion', 'competitor']},
                    'eligibility': _string(), 'tradeoffs': _string(),
                    'evidence': _string(),
                },
                'required': ['provider', 'plan', 'price', 'billing_period', 'source_url', 'offer_type', 'eligibility', 'tradeoffs', 'evidence'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['candidates'],
    'additionalProperties': False,
}

VERIFY_SCHEMA = {
    'type': 'object',
    'properties': {
        'price_supported': {'type': 'boolean'},
        'billing_period_supported': {'type': 'boolean'},
        'currently_available': {'type': 'boolean'},
        'comparable': {'type': 'boolean'},
        'source_url': _string(), 'eligibility': _string(),
        'tradeoffs': _string(), 'reason': _string(),
    },
    'required': ['price_supported', 'billing_period_supported', 'currently_available', 'comparable', 'source_url', 'eligibility', 'tradeoffs', 'reason'],
    'additionalProperties': False,
}


def parse_json(raw):
    if not raw or not raw.strip():
        raise ValueError('AI Scout returned no JSON text')
    raw = raw.strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'AI Scout returned malformed JSON near character {exc.pos}') from exc


def ai_call(client, instructions, prompt):
    schema = RESEARCH_SCHEMA if instructions == RESEARCH else VERIFY_SCHEMA
    response = client.responses.create(
        model=os.getenv('OPENAI_SCOUT_MODEL', 'gpt-5.1'),
        tools=[{'type': 'web_search'}],
        instructions=instructions,
        input=prompt,
        text={'format': {'type': 'json_schema', 'name': 'research_candidates' if schema is RESEARCH_SCHEMA else 'verified_offer', 'strict': True, 'schema': schema}},
        max_output_tokens=4500,
    )
    if response.status != 'completed':
        raise RuntimeError(f'AI Scout response not completed (status={response.status}; details={response.incomplete_details})')
    return parse_json(response.output_text)

def cents(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not Decimal('0') < amount < Decimal('100000'):
            return None
        return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return None

def https_url(url):
    try:
        p = urlparse(url)
        return p.scheme == 'https' and bool(p.hostname) and p.hostname not in ('localhost', '127.0.0.1')
    except (TypeError, ValueError):
        return False

def classify(sub, candidate, review):
    reasons = []
    for key in ('price_supported', 'billing_period_supported', 'currently_available', 'comparable'):
        if review.get(key) is not True:
            reasons.append('UNCONFIRMED_' + key.upper())
    source = review.get('source_url', '')
    if not https_url(source):
        reasons.append('MISSING_SOURCE')
    period = candidate.get('billing_period')
    amount = cents(candidate.get('price'))
    if amount is None or period not in ('monthly', 'yearly'):
        reasons.append('INVALID_PRICE')
        return None, reasons
    # Integer arithmetic: annual comparison prevents rounding errors on annual plans.
    current_annual = sub.monthly_cost_cents * 12
    target_annual = amount * (12 if period == 'monthly' else 1)
    annual_savings = current_annual - target_annual
    if annual_savings <= 0:
        reasons.append('NOT_CHEAPER')
    offer_type = str(candidate.get('offer_type', '')).lower()
    eligibility = str(review.get('eligibility') or candidate.get('eligibility') or '')
    if offer_type in ('student', 'family', 'bundle', 'promotion'):
        reasons.append('ELIGIBILITY_OR_TERMS_REQUIRED')
    if any(word in eligibility.lower() for word in ('student', 'household', 'new customer', 'eligible', 'qualif', 'verification')):
        if 'ELIGIBILITY_OR_TERMS_REQUIRED' not in reasons:
            reasons.append('ELIGIBILITY_OR_TERMS_REQUIRED')
    blocked = any(x.startswith('UNCONFIRMED_') for x in reasons) or 'MISSING_SOURCE' in reasons or 'NOT_CHEAPER' in reasons
    status = 'rejected' if blocked else ('conditional' if reasons else 'candidate')
    return {'status': status, 'reasons': reasons, 'target_monthly_cents': (target_annual + 6) // 12,
            'annual_savings_cents': annual_savings, 'source_url': source, 'eligibility': eligibility,
            'tradeoffs': str(review.get('tradeoffs') or candidate.get('tradeoffs') or ''),
            'billing_period': period, 'upfront_cents': amount if period == 'yearly' else 0}, reasons

class SwipePayload(BaseModel):
    decision: str

OPEN = ('candidate', 'conditional')


def live_savings(deal, sub):
    """Yearly saving of a deal against what the subscription costs right now (it may have been switched or edited)."""
    target_annual = deal.upfront_cents if deal.billing_period == 'yearly' else deal.target_monthly_cents * 12
    return sub.monthly_cost_cents * 12 - target_annual


@router.get('/pile')
def pile(db: Session = Depends(get_db)):
    # Cards are priced against the subscription as it is now, so a simulated switch re-prices the rest of
    # the pile and hides offers that no longer save money, without deleting anything.
    out = []
    for deal in db.scalars(select(ScoutDeal).where(ScoutDeal.status.in_(OPEN))).all():
        sub = db.get(Subscription, deal.subscription_id)
        if sub is None:
            continue
        savings = live_savings(deal, sub)
        if savings <= 0:
            continue
        item = deal.as_dict()
        item.update(current_provider=sub.provider, current_plan=sub.plan_name, current_monthly_cents=sub.monthly_cost_cents, annual_savings_cents=savings)
        out.append(item)
    out.sort(key=lambda d: d['annual_savings_cents'], reverse=True)
    return {'deals': out, 'realized_savings_cents': 0}

@router.get('/history')
def history(db: Session = Depends(get_db)):
    return {'deals': [d.as_dict() for d in db.scalars(select(ScoutDeal).order_by(ScoutDeal.id.desc())).all()]}

@router.post('/pile/{deal_id}/swipe')
def swipe(deal_id: int, payload: SwipePayload, db: Session = Depends(get_db)):
    if payload.decision not in ('approve', 'pass'):
        raise HTTPException(422, 'decision must be approve or pass')
    deal = db.get(ScoutDeal, deal_id)
    if not deal or deal.status not in OPEN:
        raise HTTPException(404, 'Deal is not in the swipe pile')
    if payload.decision == 'approve':
        sub = db.get(Subscription, deal.subscription_id)
        if sub is not None:
            # Simulated switch: the plan on the Plans page becomes the approved offer. What it replaced is
            # remembered so the switch can be undone. No provider account is touched.
            sub.switches.append(SimulatedSwitch(deal_id=deal.id, deal_status=deal.status, previous_provider=sub.provider,
                                                previous_plan_name=sub.plan_name, previous_monthly_cost_cents=sub.monthly_cost_cents))
            deal.current_plan, deal.current_monthly_cents, deal.annual_savings_cents = sub.plan_name, sub.monthly_cost_cents, live_savings(deal, sub)
            sub.provider, sub.plan_name, sub.monthly_cost_cents = deal.provider or sub.provider, deal.plan_name or sub.plan_name, deal.target_monthly_cents
    deal.status = 'mock_approved' if payload.decision == 'approve' else 'passed'
    db.add(AuditEvent(event_type='scout.mock_' + payload.decision, entity_id=deal.id, details='Simulation only; no provider action'))
    db.commit()
    return {'decision': payload.decision, 'mode': 'simulation_only', 'realized_savings_cents': 0,
            'message': 'Plan switched in the simulation. No real purchase, cancellation or account change occurred.' if payload.decision == 'approve' else 'Deal passed.'}


# One scan at a time, in a background thread. The page polls /agent/scan/status,
# so a refresh or a dropped connection no longer loses the scan.
_state_lock = threading.Lock()
_scan_state = {'running': False, 'phase': 'idle', 'done': 0, 'total': 0, 'started_at': None, 'finished_at': None, 'result': None}


def _set_state(**changes):
    with _state_lock:
        _scan_state.update(changes)


def _bump():
    with _state_lock:
        _scan_state['done'] += 1


def _snapshot():
    with _state_lock:
        return dict(_scan_state)


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.get('/scan/status')
def scan_status():
    return _snapshot()


@router.post('/scan', status_code=202)
def scan():
    if not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(503, 'Set OPENAI_API_KEY in backend/.env to enable AI scouting')
    with _state_lock:
        if _scan_state['running']:
            raise HTTPException(409, 'A scan is already running')
        _scan_state.update(running=True, phase='research', done=0, total=0, started_at=_now(), finished_at=None, result=None)
    threading.Thread(target=_scan_job, daemon=True).start()
    return _snapshot()


def _scan_job():
    try:
        result = run_scan()
    except Exception as exc:
        result = {'new_deals': 0, 'rejected': 0, 'skipped': 0, 'errors': [f'{type(exc).__name__}: {str(exc)[:160]}'], 'message': 'Scan failed.'}
    _set_state(running=False, phase='idle', finished_at=_now(), result=result)


def offer_fingerprint(sub_id, candidate):
    # Provider, price and billing period identify an offer. The plan name is left out on purpose:
    # the AI words it differently from scan to scan.
    return hashlib.sha256(json.dumps([sub_id, str(candidate.get('provider', '')).strip().casefold(), cents(candidate.get('price')), candidate.get('billing_period')]).encode()).hexdigest()


def already_seen(db, sub, candidate, assessment):
    """True if this subscription already has a deal (open, approved or passed) from the same provider at the same price."""
    provider = str(candidate.get('provider', ''))[:120].strip().lower()
    return db.scalar(select(ScoutDeal.id).where(
        ScoutDeal.subscription_id == sub.id,
        func.lower(func.trim(ScoutDeal.provider)) == provider,
        ScoutDeal.billing_period == assessment['billing_period'],
        ScoutDeal.target_monthly_cents == assessment['target_monthly_cents'],
    ).limit(1)) is not None


def run_scan():
    """Research and review run in parallel; identical subscriptions share one round of AI calls."""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=90, max_retries=1)
    workers = max(1, int(os.getenv('SCOUT_MAX_PARALLEL', '6')))
    today = datetime.now(timezone.utc).date().isoformat()
    errors = []
    found = 0
    rejected = 0
    skipped = 0
    with SessionLocal() as db:
        subs = db.scalars(select(Subscription).where(Subscription.status == 'active')).all()
        # Two entries for the same provider, plan and price would ask the AI the same questions twice.
        groups = {}
        for sub in subs:
            key = (sub.provider.strip().casefold(), sub.plan_name.strip().casefold(), sub.monthly_cost_cents)
            groups.setdefault(key, []).append(sub)
        groups = list(groups.values())

        def research(provider, plan, monthly_cents):
            try:
                result = ai_call(client, RESEARCH, json.dumps({'service': provider, 'plan': plan, 'current_monthly_usd': monthly_cents / 100, 'country': 'United States', 'date': today}))
                return result.get('candidates', [])[:5]
            finally:
                _bump()

        def verify(provider, plan, candidate):
            try:
                return ai_call(client, VERIFY, json.dumps({'subscription': {'provider': provider, 'plan': plan}, 'candidate': candidate, 'date': today}))
            finally:
                _bump()

        # Only plain values cross into worker threads; all database work stays on this thread.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            _set_state(phase='research', done=0, total=len(groups))
            research_jobs = [(g, pool.submit(research, g[0].provider, g[0].plan_name, g[0].monthly_cost_cents)) for g in groups]
            candidates = []
            for group, future in research_jobs:
                try:
                    candidates.extend((group, candidate) for candidate in future.result())
                except Exception as exc:
                    errors.append(f'{group[0].provider}: {type(exc).__name__}: {str(exc)[:120]}')
            _set_state(phase='review', done=0, total=len(candidates))
            verify_jobs = [(group, candidate, pool.submit(verify, group[0].provider, group[0].plan_name, candidate)) for group, candidate in candidates]
            for group, candidate, future in verify_jobs:
                try:
                    review = future.result()
                except Exception as exc:
                    errors.append(f'{group[0].provider} candidate: {type(exc).__name__}: {str(exc)[:120]}')
                    continue
                for sub in group:
                    try:
                        assessment, reasons = classify(sub, candidate, review)
                        if assessment is None or assessment['status'] == 'rejected':
                            rejected += 1
                            continue
                        if already_seen(db, sub, candidate, assessment):
                            # Never re-add passed or approved deals on subsequent scans, whatever the AI calls the plan this time.
                            skipped += 1
                            continue
                        deal = ScoutDeal(subscription_id=sub.id, fingerprint=offer_fingerprint(sub.id, candidate),
                            provider=str(candidate.get('provider', ''))[:120], plan_name=str(candidate.get('plan', ''))[:120],
                            current_plan=sub.plan_name, current_monthly_cents=sub.monthly_cost_cents,
                            target_monthly_cents=assessment['target_monthly_cents'],
                            annual_savings_cents=assessment['annual_savings_cents'],
                            billing_period=assessment['billing_period'], upfront_cents=assessment['upfront_cents'],
                            eligibility=assessment['eligibility'], tradeoffs=assessment['tradeoffs'],
                            source_url=assessment['source_url'], status=assessment['status'],
                            caveat='AI-assisted verification only. Check the provider before acting. This is a simulated offer.',
                            review_reason=str(review.get('reason', ''))[:2000])
                        db.add(deal)
                        db.commit()
                        found += 1
                    except Exception as exc:
                        db.rollback()
                        errors.append(f'{sub.provider} candidate: {type(exc).__name__}: {str(exc)[:120]}')
    return {'new_deals': found, 'rejected': rejected, 'skipped': skipped, 'errors': errors, 'message': 'Scan finished. Open Swipe Pile to review mock deals.'}
