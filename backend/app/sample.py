"""Sample data for demos and judges: one tap replaces everything with a known starting point.

Loads three everyday subscriptions at their US list prices (checked November 2026) plus, when PayPal is
configured, the sandbox subscription from PAYPAL_DEMO_SUBSCRIPTION_ID. If that subscription is no longer on
the Standard plan (an earlier visitor switched it), ReDeal asks PayPal to move it back; the sandbox buyer
confirms on PayPal, exactly like Undo.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditEvent, Offer, ScoutDeal, SimulatedSwitch, Subscription, SwitchRequest

router = APIRouter(prefix='/sample', tags=['Sample data'])

# (provider, plan, monthly price in cents). Real services, so the AI scan finds real offers on the web.
SAMPLE_SUBSCRIPTIONS = [
    ('Spotify', 'Premium Individual', 1299),
    ('Netflix', 'Standard', 1999),
    ('YouTube Premium', 'Individual', 1599),
]


@router.post('/load')
def load_sample_data(request: Request, db: Session = Depends(get_db)):
    """Clear all subscriptions, deals and offers, then load the sample set. The audit trail is kept."""
    for model in (ScoutDeal, SwitchRequest, Offer, SimulatedSwitch, Subscription):
        db.execute(delete(model))
    for provider, plan, cents in SAMPLE_SUBSCRIPTIONS:
        db.add(Subscription(provider=provider, category='digital', plan_name=plan, monthly_cost_cents=cents))
    db.add(AuditEvent(event_type='sample.loaded', entity_id=0, details=f'{len(SAMPLE_SUBSCRIPTIONS)} sample subscriptions'))
    db.commit()

    from . import paypal
    result = {'subscriptions': len(SAMPLE_SUBSCRIPTIONS), 'paypal': 'not_configured', 'approval_url': None}
    if not (paypal.configured() and os.getenv('PAYPAL_DEMO_SUBSCRIPTION_ID', '').strip()):
        result['message'] = 'Sample subscriptions loaded. Add PayPal sandbox settings to include a PayPal-billed plan.'
        return result
    try:
        linked = paypal.link_demo(db)
        result['subscriptions'] += 1
        result['paypal'] = 'linked'
        sub = db.get(Subscription, linked['subscription']['id'])
        live = paypal.snapshot(sub.paypal_subscription_id)['subscription']
        standard = os.getenv('PAYPAL_STANDARD_PLAN_ID', '').strip()
        if standard and live.get('status') == 'ACTIVE' and live.get('plan_id') != standard:
            # An earlier visitor switched it to a cheaper plan: put it back so the demo has a deal to find.
            result['approval_url'] = paypal.revise(sub.paypal_subscription_id, standard, str(request.base_url))
            result['paypal'] = 'reset_requested'
            db.add(AuditEvent(event_type='sample.paypal_reset', entity_id=sub.id, details='Revision back to Standard requested'))
            db.commit()
    except HTTPException as exc:
        result['paypal'] = 'error'
        result['message'] = f'Sample subscriptions loaded, but PayPal could not be reached: {exc.detail}'
        return result
    result['message'] = ('Sample data loaded. Confirm on PayPal to move the PayPal plan back to Standard.'
                         if result['approval_url'] else 'Sample data loaded.')
    return result
