import base64
import os
import secrets
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from .database import Base, add_missing_columns, engine, get_db
from .models import AuditEvent, Offer, ScoutDeal, Subscription, SwitchRequest
from .schemas import Evaluation, OfferCreate, OfferRead, SubscriptionCreate, SubscriptionRead, SwitchRead

Base.metadata.create_all(bind=engine)
add_missing_columns()
app = FastAPI(title='ReDeal API', version='0.6.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000', 'http://127.0.0.1:3000'], allow_methods=['*'], allow_headers=['*'])

# Optional password gate for public hosting. Set APP_PASSWORD (and optionally APP_USERNAME) and every
# page and API route except /health asks for it with the browser's own sign-in prompt. Unset = open, as on localhost.
_app_password = os.getenv('APP_PASSWORD', '')
if _app_password:
    _expected = (os.getenv('APP_USERNAME', 'redeal') + ':' + _app_password).encode()

    @app.middleware('http')
    async def require_password(request, call_next):
        if request.url.path == '/health':
            return await call_next(request)
        header = request.headers.get('authorization', '')
        supplied = b''
        if header[:6].lower() == 'basic ':
            try:
                supplied = base64.b64decode(header[6:], validate=True)
            except ValueError:
                supplied = b''
        if not secrets.compare_digest(supplied, _expected):
            return Response('Password required', status_code=401, headers={'WWW-Authenticate': 'Basic realm="ReDeal", charset="UTF-8"'})
        return await call_next(request)

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/subscriptions', response_model=SubscriptionRead, status_code=201)
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)):
    sub = Subscription(**payload.model_dump())
    db.add(sub)
    db.flush()
    db.add(AuditEvent(event_type='subscription.created', entity_id=sub.id, details=sub.provider))
    db.commit()
    db.refresh(sub)
    return sub

@app.get('/subscriptions', response_model=list[SubscriptionRead])
def list_subscriptions(db: Session = Depends(get_db)):
    return db.scalars(select(Subscription).order_by(Subscription.id.desc())).all()

@app.put('/subscriptions/{subscription_id}', response_model=SubscriptionRead)
def update_subscription(subscription_id: int, payload: SubscriptionCreate, db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise HTTPException(404, 'Subscription not found')
    for key, value in payload.model_dump().items():
        setattr(sub, key, value)
    # Cards still in the pile quote the old plan and price: refresh them, and drop any that no longer save money.
    open_deals = db.scalars(select(ScoutDeal).where(ScoutDeal.subscription_id == sub.id, ScoutDeal.status.in_(['candidate', 'conditional']))).all()
    for deal in open_deals:
        target_annual = deal.upfront_cents if deal.billing_period == 'yearly' else deal.target_monthly_cents * 12
        savings = sub.monthly_cost_cents * 12 - target_annual
        if savings <= 0:
            db.delete(deal)
        else:
            deal.current_plan, deal.current_monthly_cents, deal.annual_savings_cents = sub.plan_name, sub.monthly_cost_cents, savings
    db.add(AuditEvent(event_type='subscription.updated', entity_id=sub.id, details=sub.provider))
    db.commit()
    db.refresh(sub)
    return sub

@app.post('/subscriptions/{subscription_id}/undo-switch', response_model=SubscriptionRead)
def undo_switch(subscription_id: int, request: Request, db: Session = Depends(get_db)):
    """Undo the most recent switch: the plan goes back to what it replaced and the deal returns to the pile.
    For a PayPal-billed plan, ReDeal also asks PayPal to switch the subscription back."""
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise HTTPException(404, 'Subscription not found')
    if not sub.switches:
        raise HTTPException(409, 'This subscription has no switch to undo')
    last = sub.switches[-1]
    approval_url = None
    if sub.paypal_subscription_id and last.previous_paypal_plan_id:
        from .paypal import revise
        approval_url = revise(sub.paypal_subscription_id, last.previous_paypal_plan_id, str(request.base_url))
    sub.provider, sub.plan_name, sub.monthly_cost_cents = last.previous_provider, last.previous_plan_name, last.previous_monthly_cost_cents
    deal = db.get(ScoutDeal, last.deal_id) if last.deal_id else None
    if deal is not None and deal.subscription_id == sub.id and deal.status == 'mock_approved':
        deal.status = last.deal_status
    sub.switches.remove(last)
    db.add(AuditEvent(event_type='subscription.switch_undone', entity_id=sub.id,
                      details='PayPal revision requested' if last.previous_paypal_plan_id else 'Tracked in ReDeal only'))
    db.commit()
    db.refresh(sub)
    out = SubscriptionRead.model_validate(sub)
    out.paypal_approval_url = approval_url
    return out

@app.delete('/subscriptions/{subscription_id}', status_code=204)
def delete_subscription(subscription_id: int, db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise HTTPException(404, 'Subscription not found')
    # Remove everything that hangs off the subscription; the audit trail is kept.
    db.execute(delete(ScoutDeal).where(ScoutDeal.subscription_id == subscription_id))
    db.execute(delete(SwitchRequest).where(SwitchRequest.subscription_id == subscription_id))
    db.execute(delete(Offer).where(Offer.subscription_id == subscription_id))
    db.add(AuditEvent(event_type='subscription.deleted', entity_id=subscription_id, details=sub.provider))
    db.delete(sub)
    db.commit()
    return Response(status_code=204)

@app.post('/subscriptions/{subscription_id}/offers', response_model=OfferRead, status_code=201)
def create_offer(subscription_id: int, payload: OfferCreate, db: Session = Depends(get_db)):
    if db.get(Subscription, subscription_id) is None:
        raise HTTPException(404, 'Subscription not found')
    offer = Offer(subscription_id=subscription_id, **payload.model_dump(mode='json'))
    db.add(offer)
    db.flush()
    db.add(AuditEvent(event_type='offer.created', entity_id=offer.id, details=offer.provider))
    db.commit()
    db.refresh(offer)
    return offer

@app.get('/subscriptions/{subscription_id}/offers', response_model=list[OfferRead])
def list_offers(subscription_id: int, db: Session = Depends(get_db)):
    if db.get(Subscription, subscription_id) is None:
        raise HTTPException(404, 'Subscription not found')
    return db.scalars(select(Offer).where(Offer.subscription_id == subscription_id)).all()

@app.get('/subscriptions/{subscription_id}/offers/{offer_id}/evaluate', response_model=Evaluation)
def evaluate_offer(subscription_id: int, offer_id: int, months: int = Query(12, ge=1, le=120), db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    offer = db.get(Offer, offer_id)
    if sub is None or offer is None or offer.subscription_id != subscription_id:
        raise HTTPException(404, 'Subscription or offer not found')
    promo_months = min(months, offer.promotional_months)
    current = months * sub.monthly_cost_cents
    proposed = (promo_months * offer.promotional_monthly_cents
                + (months - promo_months) * offer.regular_monthly_cents
                + offer.activation_fee_cents + sub.cancellation_fee_cents)
    return Evaluation(offer_id=offer_id, horizon_months=months, current_total_cents=current,
                      offer_total_cents=proposed, estimated_savings_cents=current - proposed,
                      caveat='Estimate excludes taxes, usage, service gaps, and unverified eligibility. No switch is executed.')

@app.post('/subscriptions/{subscription_id}/offers/{offer_id}/request-switch', response_model=SwitchRead, status_code=201)
def request_switch(subscription_id: int, offer_id: int, db: Session = Depends(get_db)):
    offer = db.get(Offer, offer_id)
    if db.get(Subscription, subscription_id) is None or offer is None or offer.subscription_id != subscription_id:
        raise HTTPException(404, 'Subscription or offer not found')
    existing = db.scalar(select(SwitchRequest).where(SwitchRequest.subscription_id == subscription_id, SwitchRequest.offer_id == offer_id))
    if existing:
        raise HTTPException(409, 'Switch request already exists')
    req = SwitchRequest(subscription_id=subscription_id, offer_id=offer_id)
    db.add(req)
    db.flush()
    db.add(AuditEvent(event_type='switch.requested', entity_id=req.id, details='Awaiting explicit approval'))
    db.commit()
    db.refresh(req)
    return req

@app.get('/switch-requests', response_model=list[SwitchRead])
def list_switch_requests(db: Session = Depends(get_db)):
    return db.scalars(select(SwitchRequest).order_by(SwitchRequest.id.desc())).all()

@app.post('/switch-requests/{request_id}/approve', response_model=SwitchRead)
def approve_switch(request_id: int, db: Session = Depends(get_db)):
    req = db.get(SwitchRequest, request_id)
    if req is None:
        raise HTTPException(404, 'Switch request not found')
    if req.status != 'pending_approval':
        raise HTTPException(409, 'Request is not pending approval')
    req.status = 'approved_not_executed'
    req.approved_at = datetime.now(timezone.utc)
    db.add(AuditEvent(event_type='switch.approved', entity_id=req.id, details='No merchant action performed'))
    db.commit()
    db.refresh(req)
    return req

from .paypal import router as paypal_router
app.include_router(paypal_router)

from .deals import router as demo_router
app.include_router(demo_router)

from .scout import router as scout_router
app.include_router(scout_router)

from .agent_scout import router as agent_router
app.include_router(agent_router)

# Serve the static frontend from the same origin (mounted last so API routes win).
from fastapi.staticfiles import StaticFiles
_frontend = Path(__file__).resolve().parents[2] / 'frontend'
if _frontend.is_dir():
    app.mount('/', StaticFiles(directory=_frontend, html=True), name='frontend')
