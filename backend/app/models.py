from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Subscription(Base):
    __tablename__ = 'subscriptions'
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30))
    plan_name: Mapped[str] = mapped_column(String(120))
    monthly_cost_cents: Mapped[int] = mapped_column(Integer)
    cancellation_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    offers: Mapped[list['Offer']] = relationship(back_populates='subscription')

class Offer(Base):
    __tablename__ = 'offers'
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey('subscriptions.id'))
    provider: Mapped[str] = mapped_column(String(120))
    plan_name: Mapped[str] = mapped_column(String(120))
    promotional_monthly_cents: Mapped[int] = mapped_column(Integer)
    promotional_months: Mapped[int] = mapped_column(Integer)
    regular_monthly_cents: Mapped[int] = mapped_column(Integer)
    activation_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    eligibility_notes: Mapped[str] = mapped_column(Text, default='')
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    subscription: Mapped[Subscription] = relationship(back_populates='offers')

class SwitchRequest(Base):
    __tablename__ = 'switch_requests'
    __table_args__ = (UniqueConstraint('subscription_id', 'offer_id', name='uq_switch_subscription_offer'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey('subscriptions.id'))
    offer_id: Mapped[int] = mapped_column(ForeignKey('offers.id'))
    status: Mapped[str] = mapped_column(String(30), default='pending_approval')
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[int] = mapped_column(Integer)
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ScoutDeal(Base):
    __tablename__ = 'scout_deals'
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey('subscriptions.id'))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(120))
    plan_name: Mapped[str] = mapped_column(String(120))
    current_plan: Mapped[str] = mapped_column(String(120))
    current_monthly_cents: Mapped[int] = mapped_column(Integer)
    target_monthly_cents: Mapped[int] = mapped_column(Integer)
    annual_savings_cents: Mapped[int] = mapped_column(Integer)
    billing_period: Mapped[str] = mapped_column(String(20))
    upfront_cents: Mapped[int] = mapped_column(Integer, default=0)
    eligibility: Mapped[str] = mapped_column(Text, default='')
    tradeoffs: Mapped[str] = mapped_column(Text, default='')
    source_url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(30), default='candidate')
    caveat: Mapped[str] = mapped_column(Text, default='')
    review_reason: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def as_dict(self):
        return {key: getattr(self, key) for key in (
            'id', 'subscription_id', 'provider', 'plan_name', 'current_plan',
            'current_monthly_cents', 'target_monthly_cents', 'annual_savings_cents',
            'billing_period', 'upfront_cents', 'eligibility', 'tradeoffs',
            'source_url', 'status', 'caveat', 'review_reason')}
