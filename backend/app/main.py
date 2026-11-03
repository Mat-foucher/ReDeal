from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import AuditEvent, Offer, Subscription, SwitchRequest
from .schemas import Evaluation, OfferCreate, OfferRead, SubscriptionCreate, SubscriptionRead, SwitchRead

Base.metadata.create_all(bind=engine)  # MVP only; replace with Alembic migrations before production
app = FastAPI(title='ReDealer API', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000', 'http://127.0.0.1:3000'], allow_methods=['*'], allow_headers=['*'])

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
