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


def test_update_and_delete_subscription():
    from app.models import ScoutDeal
    sub = client.post('/subscriptions', json={'provider': 'EditCo', 'category': 'digital', 'plan_name': 'Plus', 'monthly_cost_cents': 2000}).json()
    with Session(engine) as db:
        for i, target in enumerate((1500, 1900)):
            db.add(ScoutDeal(subscription_id=sub['id'], fingerprint=f'edit-test-{i}', provider='Alt', plan_name=f'Alt {i}', current_plan='Plus',
                             current_monthly_cents=2000, target_monthly_cents=target, annual_savings_cents=(2000 - target) * 12,
                             billing_period='monthly', source_url='https://example.com'))
        db.commit()
    updated = client.put(f"/subscriptions/{sub['id']}", json={'provider': 'EditCo', 'category': 'mobile', 'plan_name': 'Basic', 'monthly_cost_cents': 1800})
    assert updated.status_code == 200 and updated.json()['monthly_cost_cents'] == 1800 and updated.json()['category'] == 'mobile'
    mine = [d for d in client.get('/agent/pile').json()['deals'] if d['subscription_id'] == sub['id']]
    # The 19.00 offer no longer beats 18.00 and is dropped; the 15.00 one is re-priced.
    assert [(d['target_monthly_cents'], d['annual_savings_cents'], d['current_plan']) for d in mine] == [(1500, 3600, 'Basic')]
    assert client.put('/subscriptions/999999', json={'provider': 'X', 'category': 'other', 'plan_name': 'Y', 'monthly_cost_cents': 1}).status_code == 404
    assert client.delete(f"/subscriptions/{sub['id']}").status_code == 204
    assert all(s['id'] != sub['id'] for s in client.get('/subscriptions').json())
    assert all(d['subscription_id'] != sub['id'] for d in client.get('/agent/history').json()['deals'])
    assert client.delete(f"/subscriptions/{sub['id']}").status_code == 404


def test_approve_switches_plan_and_undo_restores_it():
    from app.models import ScoutDeal
    sub = client.post('/subscriptions', json={'provider': 'Netflix', 'category': 'digital', 'plan_name': 'Standard', 'monthly_cost_cents': 2500}).json()
    assert sub['switch'] is None
    with Session(engine) as db:
        rows = [ScoutDeal(subscription_id=sub['id'], fingerprint=f'switch-test-{i}', provider=prov, plan_name=plan, current_plan='Standard',
                          current_monthly_cents=2500, target_monthly_cents=target, annual_savings_cents=(2500 - target) * 12,
                          billing_period='monthly', source_url='https://example.com', status=status)
                for i, (prov, plan, target, status) in enumerate([('Disney+', 'Bundle', 1299, 'conditional'), ('Netflix', 'Ads', 799, 'candidate'), ('Max', 'Basic', 1699, 'candidate')])]
        db.add_all(rows); db.commit()
        bundle, ads, maxb = (r.id for r in rows)
    mine = lambda: {d['id']: d for d in client.get('/agent/pile').json()['deals'] if d['subscription_id'] == sub['id']}
    assert set(mine()) == {bundle, ads, maxb}
    assert client.post(f'/agent/pile/{bundle}/swipe', json={'decision': 'approve'}).status_code == 200
    now = next(s for s in client.get('/subscriptions').json() if s['id'] == sub['id'])
    assert (now['provider'], now['plan_name'], now['monthly_cost_cents']) == ('Disney+', 'Bundle', 1299)
    assert now['switch'] == {'original_provider': 'Netflix', 'original_plan_name': 'Standard', 'original_monthly_cost_cents': 2500, 'steps': 1}
    # The pile is re-priced against the new plan: the 16.99 offer is hidden, the 7.99 one now saves (12.99-7.99)*12.
    assert {k: v['annual_savings_cents'] for k, v in mine().items()} == {ads: 6000}
    assert mine()[ads]['current_plan'] == 'Bundle'
    undone = client.post(f"/subscriptions/{sub['id']}/undo-switch")
    assert undone.status_code == 200 and undone.json()['provider'] == 'Netflix' and undone.json()['monthly_cost_cents'] == 2500 and undone.json()['switch'] is None
    assert set(mine()) == {bundle, ads, maxb} and mine()[bundle]['status'] == 'conditional'
    assert client.post(f"/subscriptions/{sub['id']}/undo-switch").status_code == 409
    client.delete(f"/subscriptions/{sub['id']}")


def test_paypal_plan_found_switched_and_undone(monkeypatch):
    """A plan billed via PayPal: the agent finds the cheaper catalog plan, approval revises it at PayPal, undo reverts."""
    from app import agent_scout, paypal
    from app.models import Subscription
    plan = lambda pid, name, price: {'id': pid, 'name': name, 'product_id': 'PROD-1', 'status': 'ACTIVE', 'description': 'Demo',
        'billing_cycles': [{'tenure_type': 'REGULAR', 'frequency': {'interval_unit': 'MONTH', 'interval_count': 1},
                            'pricing_scheme': {'fixed_price': {'value': price, 'currency_code': 'USD'}}}]}
    plans = {'P-STD': plan('P-STD', 'Standard', '25'), 'P-SAV': plan('P-SAV', 'Saver', '15')}
    state = {'plan': 'P-STD', 'revisions': []}

    def fake_paypal(method, path, body=None):
        if path == '/v1/billing/subscriptions/I-TEST1':
            return {'id': 'I-TEST1', 'status': 'ACTIVE', 'plan_id': state['plan']}
        if path.startswith('/v1/billing/plans?'):
            return {'plans': [{'id': p, 'status': 'ACTIVE'} for p in plans]}
        if path.startswith('/v1/billing/plans/'):
            return plans[path.rsplit('/', 1)[1]]
        if path == '/v1/catalogs/products/PROD-1':
            return {'name': 'Demo Membership'}
        if path == '/v1/billing/subscriptions/I-TEST1/revise':
            state['revisions'].append(body['plan_id'])
            return {'links': [{'rel': 'approve', 'href': 'https://www.sandbox.paypal.com/approve'}]}
        raise AssertionError(path)

    monkeypatch.setattr(paypal, 'paypal_request', fake_paypal)
    monkeypatch.setattr(agent_scout, 'ai_compare', lambda client, cur, new: {'comparable': True, 'eligibility': 'Any subscriber', 'tradeoffs': 'None listed', 'reason': 'Same service, lower price.'})
    monkeypatch.setenv('PAYPAL_DEMO_SUBSCRIPTION_ID', 'I-TEST1')

    linked = client.post('/paypal/link-demo').json()
    assert linked['created'] and linked['subscription']['provider'] == 'Demo Membership'
    assert linked['subscription']['monthly_cost_cents'] == 2500 and linked['subscription']['paypal_subscription_id'] == 'I-TEST1'
    assert client.post('/paypal/link-demo').json()['created'] is False
    sid = linked['subscription']['id']

    with Session(engine) as db:
        assert agent_scout.scan_paypal(db, None, db.get(Subscription, sid)) == (1, 0, 0)
        assert agent_scout.scan_paypal(db, None, db.get(Subscription, sid)) == (0, 0, 1)  # already in the pile
    deal = next(d for d in client.get('/agent/pile').json()['deals'] if d['subscription_id'] == sid)
    assert (deal['paypal_plan_id'], deal['annual_savings_cents'], deal['status']) == ('P-SAV', 12000, 'candidate')

    r = client.post(f"/agent/pile/{deal['id']}/swipe", json={'decision': 'approve'}).json()
    assert r['mode'] == 'paypal' and r['approval_url'] and state['revisions'] == ['P-SAV']
    now = next(s for s in client.get('/subscriptions').json() if s['id'] == sid)
    assert (now['plan_name'], now['monthly_cost_cents']) == ('Saver', 1500)

    state['plan'] = 'P-SAV'  # the buyer confirmed on PayPal
    back = client.post(f'/subscriptions/{sid}/undo-switch').json()
    assert state['revisions'] == ['P-SAV', 'P-STD'] and back['paypal_approval_url'] and back['monthly_cost_cents'] == 2500
    client.delete(f'/subscriptions/{sid}')
