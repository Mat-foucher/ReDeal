"""Public-page discovery -> simulated deal cards. No third-party purchase actions."""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import get_db, SessionLocal
from .models import Subscription

router = APIRouter(prefix='/scout', tags=['Public web scout (mock actions)'])
SOURCE_FILE = Path(__file__).resolve().parents[1] / 'scout_sources.json'
# Volatile prototype cache. In production use per-user DB rows and background jobs.
_cache = {'deals': [], 'errors': [], 'scanned_at': None}
_decisions = {}  # demo only; resets on restart
_scan_lock = asyncio.Lock()


def money_to_cents(value):
    try:
        amount = Decimal(str(value).replace(',', '').replace('$', '').strip())
        if amount <= 0 or amount > 10000:
            return None
        return int((amount * 100).quantize(Decimal('1')))
    except (InvalidOperation, ValueError):
        return None


def extract_jsonld_offers(html):
    """Extract explicit USD offers from publisher-supplied structured data only."""
    matches = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    found = []
    def walk(node, parent=''):
        if isinstance(node, list):
            for child in node: walk(child, parent)
        elif isinstance(node, dict):
            kind = node.get('@type', '')
            types = kind if isinstance(kind, list) else [kind]
            name = str(node.get('name') or parent or 'Published offer')[:120]
            if 'Offer' in types or 'AggregateOffer' in types:
                price = node.get('price') or (node.get('priceSpecification') or {}).get('price') if isinstance(node.get('priceSpecification'), dict) else node.get('price')
                currency = node.get('priceCurrency') or (node.get('priceSpecification') or {}).get('priceCurrency') if isinstance(node.get('priceSpecification'), dict) else node.get('priceCurrency')
                # Do not assume one-time prices are monthly. Require explicit month billing metadata.
                spec = node.get('priceSpecification') if isinstance(node.get('priceSpecification'), dict) else {}
                unit = str(spec.get('billingDuration') or spec.get('unitText') or node.get('billingDuration') or '').lower()
                if currency == 'USD' and (unit in ('p1m', 'month', 'monthly', '1 month') or 'month' in unit):
                    cents = money_to_cents(price)
                    if cents is not None: found.append({'name': name, 'monthly_cents': cents})
            for k, v in node.items():
                if isinstance(v, (list, dict)): walk(v, name)
    for match in matches:
        try: walk(json.loads(match))
        except (ValueError, TypeError): continue
    return found


def extract_explicit_monthly(html):
    """Conservative fallback: visible $X/month text; no guessing annual/intro rates."""
    from html import unescape
    cleaned = re.sub(r'<(script|style|noscript)\b[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
    cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    amounts = re.findall(r'\$\s*(\d{1,4}(?:\.\d{1,2})?)\s*(?:/\s*(?:mo|month)\b|per\s+month\b)', cleaned, re.I)
    return sorted({c for x in amounts if (c := money_to_cents(x)) is not None})


class MockDecision(BaseModel):
    deal_id: str
    decision: str


async def run_agent(db: Session):
    if not SOURCE_FILE.exists():
        raise HTTPException(503, 'Missing backend/scout_sources.json')
    sources = json.loads(SOURCE_FILE.read_text())
    subs = db.scalars(select(Subscription).where(Subscription.status == 'active')).all()
    deals, errors = [], []
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers={'User-Agent': 'ReDealerPrototypeScout/0.4 (public pricing research)'}) as client:
        for source in sources:
            provider, url = source.get('provider', ''), source.get('url', '')
            matching = [s for s in subs if s.provider.strip().casefold() == provider.strip().casefold()]
            if not matching: continue
            parsed = urlparse(url)
            # URLs are developer-maintained in a local config, never accepted from user input.
            if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname in ('localhost', '127.0.0.1'):
                errors.append({'provider': provider, 'reason': 'Invalid HTTPS source URL'}); continue
            try:
                response = await client.get(url)
                response.raise_for_status()
                if 'text/html' not in response.headers.get('content-type', ''):
                    raise ValueError('Source is not HTML')
                html = response.text[:750000]
                offers = extract_jsonld_offers(html)
                if not offers:
                    offers = [{'name': 'Publicly advertised monthly price (plan unverified)', 'monthly_cents': cents} for cents in extract_explicit_monthly(html)]
                if not offers:
                    errors.append({'provider': provider, 'reason': 'No explicit monthly USD pricing found; no deal invented'})
                for sub in matching:
                    for offer in offers:
                        if offer['monthly_cents'] >= sub.monthly_cost_cents: continue
                        key = f"web-{sub.id}-{offer['monthly_cents']}"
                        deals.append({'id': key, 'provider': provider, 'subscription_id': sub.id,
                            'current_plan': sub.plan_name, 'target_plan': offer['name'],
                            'current_monthly_cents': sub.monthly_cost_cents,
                            'target_monthly_cents': offer['monthly_cents'],
                            'estimated_annual_savings_cents': (sub.monthly_cost_cents - offer['monthly_cents']) * 12,
                            'source_url': url, 'source_type': 'public_web', 'mode': 'simulation_only',
                            'caveat': 'Public price spotted; plan equivalence, eligibility, fees, taxes, and promo duration NOT verified. Simulated switch only.'})
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({'provider': provider, 'reason': f'{type(exc).__name__}: {str(exc)[:160]}'})
    deals = [d for d in deals if _decisions.get(d['id']) != 'pass']
    _cache.update(deals=deals[:50], errors=errors, scanned_at=datetime.now(timezone.utc).isoformat())
    return _cache


@router.post('/scan')
async def scan(db: Session = Depends(get_db)):
    if _scan_lock.locked():
        return _cache
    async with _scan_lock:
        return await run_agent(db)


async def periodic_agent():
    """Run automatically while the API is up. One process only for MVP."""
    interval = max(300, int(os.getenv('SCOUT_INTERVAL_SECONDS', '1800')))
    while True:
        try:
            async with _scan_lock:
                with SessionLocal() as db:
                    await run_agent(db)
        except Exception as exc:
            _cache['errors'] = [{'provider': 'Scout', 'reason': f'{type(exc).__name__}: {str(exc)[:120]}'}]
        await asyncio.sleep(interval)


@router.get('/deals')
def list_scanned():
    return _cache


@router.post('/mock-decision')
def mock_decision(payload: MockDecision):
    if payload.decision not in ('approve', 'pass'):
        raise HTTPException(422, 'decision must be approve or pass')
    deal = next((d for d in _cache['deals'] if d['id'] == payload.deal_id), None)
    if deal is None: raise HTTPException(404, 'Scan first; deal not found')
    _decisions[payload.deal_id] = payload.decision
    if payload.decision == 'pass':
        _cache['deals'] = [d for d in _cache['deals'] if d['id'] != payload.deal_id]
    return {'mode': 'simulation_only', 'decision': payload.decision,
            'message': 'Simulated approval recorded for this session. No payment, purchase, cancellation, or provider account change was made.' if payload.decision == 'approve' else 'Passed on simulated offer. No action taken.',
            'projected_annual_savings_cents': deal['estimated_annual_savings_cents'] if payload.decision == 'approve' else 0,
            'realized_savings_cents': 0}
