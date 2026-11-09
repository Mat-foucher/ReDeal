from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from typing import Literal

class SubscriptionCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=120)
    category: Literal['digital', 'internet', 'mobile', 'utility', 'other']
    plan_name: str = Field(min_length=1, max_length=120)
    monthly_cost_cents: int = Field(ge=0)
    cancellation_fee_cents: int = Field(default=0, ge=0)

class SimulatedSwitchInfo(BaseModel):
    original_provider: str
    original_plan_name: str
    original_monthly_cost_cents: int
    steps: int

class SubscriptionRead(SubscriptionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    switch: SimulatedSwitchInfo | None = None

class OfferCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=120)
    plan_name: str = Field(min_length=1, max_length=120)
    promotional_monthly_cents: int = Field(ge=0)
    promotional_months: int = Field(ge=0, le=120)
    regular_monthly_cents: int = Field(ge=0)
    activation_fee_cents: int = Field(default=0, ge=0)
    eligibility_notes: str = ''
    source_url: HttpUrl | None = None

class OfferRead(OfferCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subscription_id: int

class Evaluation(BaseModel):
    offer_id: int
    horizon_months: int
    current_total_cents: int
    offer_total_cents: int
    estimated_savings_cents: int
    caveat: str

class SwitchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subscription_id: int
    offer_id: int
    status: str
