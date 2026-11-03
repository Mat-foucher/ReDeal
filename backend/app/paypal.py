"""PayPal sandbox demo integration. Never put client credentials in the browser."""
import os
from typing import Any
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix='/paypal', tags=['PayPal sandbox'])
BASE = 'https://api-m.sandbox.paypal.com'


def config():
    if os.getenv('PAYPAL_ENVIRONMENT', 'sandbox') != 'sandbox':
        raise HTTPException(503, 'This demo only supports PayPal sandbox')
    cid, secret = os.getenv('PAYPAL_CLIENT_ID'), os.getenv('PAYPAL_CLIENT_SECRET')
    if not cid or not secret:
        raise HTTPException(503, 'PayPal credentials not configured')
    return cid, secret


async def paypal_call(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    cid, secret = config()
    async with httpx.AsyncClient(timeout=25) as client:
        token_response = await client.post(BASE + '/v1/oauth2/token', auth=(cid, secret), data={'grant_type': 'client_credentials'})
        if token_response.is_error:
            raise HTTPException(502, 'PayPal OAuth failed; verify sandbox credentials')
        token = token_response.json()['access_token']
        response = await client.request(method, BASE + path, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'Prefer': 'return=representation'}, json=body)
    if response.is_error:
        # Do not leak provider error payloads or credentials to clients.
        raise HTTPException(502, f'PayPal request failed (HTTP {response.status_code})')
    return response.json() if response.content else {}


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
    if not subscription_id.startswith('I-') or len(subscription_id) > 64:
        raise HTTPException(422, 'Invalid subscription ID')
    data = await paypal_call('GET', '/v1/billing/subscriptions/' + subscription_id)
    return {'id': data.get('id'), 'status': data.get('status'), 'plan_id': data.get('plan_id'), 'billing_info': data.get('billing_info')}


# Plan revision deliberately not exposed until authenticated user ownership,
# explicit consent, approval redirect handling and webhook verification exist.
