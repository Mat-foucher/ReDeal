import os
os.environ['DATABASE_URL'] = 'sqlite://'
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app import database
from app.database import Base
from app.main import app

# Share a single in-memory database across TestClient threads.
database.engine.dispose()
from sqlalchemy import create_engine
engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
from sqlalchemy.orm import Session

def override_db():
    with Session(engine) as session:
        yield session
app.dependency_overrides[database.get_db] = override_db
client = TestClient(app)

def test_subscription_offer_approval_flow():
    sub = client.post('/subscriptions', json={'provider':'ExampleNet','category':'internet','plan_name':'Standard','monthly_cost_cents':8000,'cancellation_fee_cents':2000})
    assert sub.status_code == 201
    sid = sub.json()['id']
    offer = client.post(f'/subscriptions/{sid}/offers', json={'provider':'BetterNet','plan_name':'Promo','promotional_monthly_cents':4000,'promotional_months':6,'regular_monthly_cents':7000,'activation_fee_cents':1000})
    assert offer.status_code == 201
    oid = offer.json()['id']
    evaluation = client.get(f'/subscriptions/{sid}/offers/{oid}/evaluate?months=12').json()
    assert evaluation['current_total_cents'] == 96000
    assert evaluation['offer_total_cents'] == 69000
    assert evaluation['estimated_savings_cents'] == 27000
    req = client.post(f'/subscriptions/{sid}/offers/{oid}/request-switch')
    assert req.status_code == 201
    assert req.json()['status'] == 'pending_approval'
    approved = client.post(f"/switch-requests/{req.json()['id']}/approve")
    assert approved.json()['status'] == 'approved_not_executed'
    assert client.post(f"/switch-requests/{req.json()['id']}/approve").status_code == 409
