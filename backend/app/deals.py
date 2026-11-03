"""Local-only PayPal sandbox demo: discovery, explicit consent and revision."""
import hmac
import os
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from .paypal import paypal_call

router = APIRouter(prefix='/demo', tags=['Automated deal demo'])


def settings():
    subscription = os.getenv('PAYPAL_DEMO_SUBSCRIPTION_ID', '').strip()
    standard = os.getenv('PAYPAL_STANDARD_PLAN_ID', '').strip()
    saver = os.getenv('PAYPAL_SAVER_PLAN_ID', '').strip()
    if not all((subscription, standard, saver)):
        raise HTTPException(503, 'Set PAYPAL_DEMO_SUBSCRIPTION_ID and both PAYPAL plan IDs in backend/.env')
    return subscription, standard, saver


async def snapshot():
    subscription_id, standard, saver = settings()
    data = await paypal_call('GET', f'/v1/billing/subscriptions/{subscription_id}')
    return data, subscription_id, standard, saver


@router.get('/deals')
async def discover_deals():
    data, sid, standard, saver = await snapshot()
    current = data.get('plan_id')
    status = data.get('status')
    # Never invent eligibility or compare arbitrary plans: this sandbox catalog is configured by us.
    deals = []
    if current == standard and status == 'ACTIVE':
        deals.append({
            'id': 'paypal-saver', 'subscription_id': sid,
            'provider': 'ReDealer Sandbox', 'current_plan': 'Standard', 'target_plan': 'Saver',
            'current_monthly_cents': 2500, 'target_monthly_cents': 1500,
            'estimated_annual_savings_cents': 12000,
            'caveat': 'Sandbox merchant catalog demo. Future billing may be prorated; savings are projected, not realized.',
            'requires_approval': True,
        })
    return {'subscription': {'id': sid, 'status': status, 'plan_id': current,
                             'current_plan': 'Standard' if current == standard else 'Saver' if current == saver else 'Unknown',
                             'last_payment': data.get('billing_info', {}).get('last_payment'),
                             'next_billing_time': data.get('billing_info', {}).get('next_billing_time')},
            'deals': deals, 'realized_savings_cents': 0,
            'note': 'Realized savings stay zero until lower-priced billing is verified against a baseline.'}


class ReviseConsent(BaseModel):
    deal_id: str
    approve: bool


@router.post('/revise')
async def revise(payload: ReviseConsent, x_demo_action_key: str | None = Header(default=None)):
    if os.getenv('PAYPAL_ENVIRONMENT', 'sandbox') != 'sandbox':
        raise HTTPException(403, 'Sandbox only')
    expected_key = os.getenv('PAYPAL_DEMO_ACTION_KEY', '')
    if len(expected_key) < 16 or not x_demo_action_key or not hmac.compare_digest(expected_key, x_demo_action_key):
        raise HTTPException(403, 'Invalid local demo action key')
    if not payload.approve or payload.deal_id != 'paypal-saver':
        raise HTTPException(422, 'Explicit approval for paypal-saver is required')
    data, sid, standard, saver = await snapshot()
    if data.get('status') != 'ACTIVE' or data.get('plan_id') != standard:
        raise HTTPException(409, 'Subscription is not an active Standard plan; refresh deals')
    # PayPal revision may return an approval link; buyer authorization must be completed there.
    result = await paypal_call('POST', f'/v1/billing/subscriptions/{sid}/revise', {'plan_id': saver})
    approval_url = next((link.get('href') for link in result.get('links', []) if link.get('rel') == 'approve'), None)
    return {'status': 'buyer_approval_required' if approval_url else 'revision_requested',
            'approval_url': approval_url, 'subscription_id': sid,
            'message': 'Revision requested. Re-check subscription plan and billing before claiming savings.'}
