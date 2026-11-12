"""PayPal sandbox integration. Never put client credentials in the browser.

ReDeal's agent loop for PayPal-billed plans:
  1. read the subscription and the merchant's plan catalog from PayPal (Subscriptions + Catalog APIs),
  2. let the AI scout compare the cheaper plans (agent_scout.py),
  3. on the user's approval in the Swipe Pile, ask PayPal to revise the subscription to the cheaper plan;
     the buyer confirms the change on PayPal's own approval page.
"""
import os
import threading
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditEvent, Subscription

router = APIRouter(prefix='/paypal', tags=['PayPal sandbox'])
BASE = 'https://api-m.sandbox.paypal.com'
# Where a sandbox buyer manages their PayPal subscriptions; used as the "source" link on PayPal deals.
BUYER_SUBSCRIPTIONS_URL = 'https://www.sandbox.paypal.com/myaccount/autopay/'


def config():
    if os.getenv('PAYPAL_ENVIRONMENT', 'sandbox') != 'sandbox':
        raise HTTPException(503, 'This demo only supports PayPal sandbox')
    cid, secret = os.getenv('PAYPAL_CLIENT_ID'), os.getenv('PAYPAL_CLIENT_SECRET')
    if not cid or not secret:
        raise HTTPException(503, 'PayPal credentials not configured')
    return cid, secret


def configured() -> bool:
    return os.getenv('PAYPAL_ENVIRONMENT', 'sandbox') == 'sandbox' and bool(os.getenv('PAYPAL_CLIENT_ID')) and bool(os.getenv('PAYPAL_CLIENT_SECRET'))


def paypal_request(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    """Synchronous PayPal REST call (OAuth client-credentials, then the request)."""
    cid, secret = config()
    with httpx.Client(timeout=25) as client:
        token_response = client.post(BASE + '/v1/oauth2/token', auth=(cid, secret), data={'grant_type': 'client_credentials'})
        if token_response.is_error:
            raise HTTPException(502, 'PayPal OAuth failed; verify sandbox credentials')
        token = token_response.json()['access_token']
        response = client.request(method, BASE + path, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'Prefer': 'return=representation'}, json=body)
    if response.is_error:
        # Do not leak provider error payloads or credentials to clients.
        raise HTTPException(502, f'PayPal request failed (HTTP {response.status_code})')
    return response.json() if response.content else {}


async def paypal_call(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    return await run_in_threadpool(paypal_request, method, path, body)


def _valid_id(value: str, prefix: str) -> bool:
    return isinstance(value, str) and value.startswith(prefix) and 3 < len(value) <= 64 and value.replace('-', '').isalnum()


# ---------- Catalog helpers ----------

def plan_price(plan: dict) -> tuple[int, str] | None:
    """(price in cents, 'monthly' | 'yearly') of a plan's regular billing cycle, or None if it isn't a simple USD plan."""
    for cycle in plan.get('billing_cycles', []):
        if cycle.get('tenure_type') != 'REGULAR':
            continue
        freq = cycle.get('frequency', {})
        price = cycle.get('pricing_scheme', {}).get('fixed_price', {})
        if price.get('currency_code') != 'USD' or freq.get('interval_count') != 1:
            return None
        period = {'MONTH': 'monthly', 'YEAR': 'yearly'}.get(freq.get('interval_unit'))
        try:
            cents = int((Decimal(str(price.get('value'))) * 100).to_integral_value())
        except (InvalidOperation, TypeError):
            return None
        return (cents, period) if period and cents > 0 else None
    return None


def monthly_cents(price: tuple[int, str]) -> int:
    cents, period = price
    return cents if period == 'monthly' else (cents + 6) // 12


def get_plan(plan_id: str) -> dict:
    return paypal_request('GET', f'/v1/billing/plans/{plan_id}')


def product_name(product_id: str) -> str:
    try:
        return paypal_request('GET', f'/v1/catalogs/products/{product_id}').get('name') or 'PayPal merchant'
    except HTTPException:
        return 'PayPal merchant'


def catalog(product_id: str) -> list[dict]:
    """All ACTIVE plans the merchant offers for this product, with full pricing."""
    listing = paypal_request('GET', f'/v1/billing/plans?product_id={product_id}&page_size=20')
    plans = []
    for item in listing.get('plans', []):
        if item.get('status') == 'ACTIVE' and _valid_id(item.get('id', ''), 'P-'):
            plans.append(get_plan(item['id']))
    return plans


def snapshot(paypal_subscription_id: str) -> dict:
    """Live state of a PayPal subscription plus its current plan."""
    if not _valid_id(paypal_subscription_id, 'I-'):
        raise HTTPException(422, 'Invalid PayPal subscription ID')
    sub = paypal_request('GET', f'/v1/billing/subscriptions/{paypal_subscription_id}')
    plan = get_plan(sub['plan_id']) if sub.get('plan_id') else {}
    return {'subscription': sub, 'plan': plan}


def sync_subscription(db: Session, sub: Subscription) -> dict:
    """Copy the plan and price PayPal is billing into the ReDeal subscription."""
    snap = snapshot(sub.paypal_subscription_id)
    plan, price = snap['plan'], plan_price(snap['plan'])
    status = snap['subscription'].get('status')
    if plan.get('name'):
        sub.plan_name = plan['name'][:120]
    if price:
        sub.monthly_cost_cents = monthly_cents(price)
    sub.status = 'active' if status == 'ACTIVE' else 'paused'
    return snap


def revise(paypal_subscription_id: str, plan_id: str, return_base: str | None) -> str | None:
    """Ask PayPal to move the subscription to another plan. Returns PayPal's buyer-approval URL, if any."""
    if not _valid_id(plan_id, 'P-'):
        raise HTTPException(422, 'Invalid PayPal plan ID')
    body: dict[str, Any] = {'plan_id': plan_id}
    if return_base:
        body['application_context'] = {
            'brand_name': 'ReDeal', 'shipping_preference': 'NO_SHIPPING', 'user_action': 'CONTINUE',
            'return_url': return_base.rstrip('/') + '/?paypal=approved#subs',
            'cancel_url': return_base.rstrip('/') + '/?paypal=cancelled#subs',
        }
    try:
        result = paypal_request('POST', f'/v1/billing/subscriptions/{paypal_subscription_id}/revise', body)
    except HTTPException:
        if 'application_context' not in body:
            raise
        # Some sandbox setups reject non-public return URLs; PayPal then uses its own pages.
        body.pop('application_context')
        result = paypal_request('POST', f'/v1/billing/subscriptions/{paypal_subscription_id}/revise', body)
    return next((link.get('href') for link in result.get('links', []) if link.get('rel') == 'approve'), None)


# ---------- Routes ----------

class StartSubscription(BaseModel):
    plan: str  # standard or saver


@router.get('/demo-plans')
def demo_plans():
    return {'standard': os.getenv('PAYPAL_STANDARD_PLAN_ID'), 'saver': os.getenv('PAYPAL_SAVER_PLAN_ID'), 'sandbox_only': True}


@router.post('/subscriptions/create')
async def start_subscription(payload: StartSubscription):
    if payload.plan not in ('standard', 'saver'):
        raise HTTPException(422, 'Plan must be standard or saver')
    plan_id = os.getenv('PAYPAL_' + payload.plan.upper() + '_PLAN_ID')
    if not plan_id:
        raise HTTPException(503, 'Run setup_paypal_plans.py and configure plan IDs first')
    data = await paypal_call('POST', '/v1/billing/subscriptions', {'plan_id': plan_id})
    approval = next((link['href'] for link in data.get('links', []) if link.get('rel') == 'approve'), None)
    return {'subscription_id': data.get('id'), 'status': data.get('status'), 'approval_url': approval}


@router.get('/subscriptions/{subscription_id}')
async def get_subscription(subscription_id: str):
    if not _valid_id(subscription_id, 'I-'):
        raise HTTPException(422, 'Invalid subscription ID')
    data = await paypal_call('GET', '/v1/billing/subscriptions/' + subscription_id)
    return {'id': data.get('id'), 'status': data.get('status'), 'plan_id': data.get('plan_id'), 'billing_info': data.get('billing_info')}


def remove_duplicate_links(db: Session) -> int:
    """Keep one ReDeal plan per PayPal subscription (the oldest); delete any extras and what hangs off them.
    Duplicates came from two imports racing each other, e.g. a double tap. Returns how many were removed."""
    from sqlalchemy import delete
    from .models import Offer, ScoutDeal, SimulatedSwitch, SwitchRequest
    seen, removed = set(), 0
    for sub in db.scalars(select(Subscription).where(Subscription.paypal_subscription_id.is_not(None)).order_by(Subscription.id)).all():
        if sub.paypal_subscription_id not in seen:
            seen.add(sub.paypal_subscription_id)
            continue
        for model in (ScoutDeal, SwitchRequest, Offer, SimulatedSwitch):
            db.execute(delete(model).where(model.subscription_id == sub.id))
        db.delete(sub)
        removed += 1
    if removed:
        db.add(AuditEvent(event_type='subscription.duplicates_removed', entity_id=0, details=f'{removed} duplicate PayPal plan(s)'))
        db.commit()
    return removed


_link_lock = threading.Lock()


@router.post('/link-demo')
def link_demo(db: Session = Depends(get_db)):
    """Add the sandbox subscription from PAYPAL_DEMO_SUBSCRIPTION_ID to Plans, priced from PayPal."""
    sid = os.getenv('PAYPAL_DEMO_SUBSCRIPTION_ID', '').strip()
    if not sid:
        raise HTTPException(503, 'Set PAYPAL_DEMO_SUBSCRIPTION_ID in backend/.env first')
    with _link_lock:   # two taps at once must not both create it
        return _link(db, sid)


def _link(db: Session, sid: str):
    remove_duplicate_links(db)
    sub = db.scalar(select(Subscription).where(Subscription.paypal_subscription_id == sid))
    created = sub is None
    if created:
        sub = Subscription(provider='PayPal merchant', category='digital', plan_name='Plan', monthly_cost_cents=0,
                           paypal_subscription_id=sid)
    snap = sync_subscription(db, sub)
    if created:
        sub.provider = product_name(snap['plan'].get('product_id', ''))[:120] if snap['plan'].get('product_id') else 'PayPal merchant'
        db.add(sub)
        db.flush()
        db.add(AuditEvent(event_type='subscription.linked_paypal', entity_id=sub.id, details=sid))
    db.commit()
    db.refresh(sub)
    from .schemas import SubscriptionRead
    return {'created': created, 'subscription': SubscriptionRead.model_validate(sub).model_dump()}


@router.post('/sync')
def sync_all(db: Session = Depends(get_db)):
    """Refresh every PayPal-billed plan from PayPal (after the buyer returns from an approval page, say)."""
    if not configured():
        return {'synced': 0, 'errors': []}
    remove_duplicate_links(db)
    synced, errors = 0, []
    for sub in db.scalars(select(Subscription).where(Subscription.paypal_subscription_id.is_not(None))).all():
        try:
            sync_subscription(db, sub)
            synced += 1
        except HTTPException as exc:
            errors.append(f'{sub.provider}: {exc.detail}')
    db.commit()
    return {'synced': synced, 'errors': errors}
