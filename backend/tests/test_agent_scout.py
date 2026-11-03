from types import SimpleNamespace
from app.agent_scout import classify, cents

sub = SimpleNamespace(monthly_cost_cents=1599)
verified = dict(price_supported=True, billing_period_supported=True, currently_available=True, comparable=True, source_url='https://example.com/plan', eligibility='', tradeoffs='')

def test_duo_not_cheaper():
    result, reasons = classify(sub, dict(price=16.99,billing_period='monthly',offer_type='family'), verified)
    assert result['status'] == 'rejected'
    assert 'NOT_CHEAPER' in reasons

def test_student_is_conditional():
    result, _ = classify(sub, dict(price=6.99,billing_period='monthly',offer_type='student'), verified)
    assert result['status'] == 'conditional'
    assert result['annual_savings_cents'] == 10800

def test_unverified_rejected():
    result, _ = classify(sub, dict(price=11.99,billing_period='monthly',offer_type='competitor'), {**verified,'currently_available':False})
    assert result['status'] == 'rejected'

def test_annual_billing():
    result, _ = classify(sub, dict(price=99,billing_period='yearly',offer_type='standard'), verified)
    assert result['annual_savings_cents'] == 9288
    assert result['upfront_cents'] == 9900

def test_invalid_price():
    assert cents('nan') is None
    result, _ = classify(sub, dict(price='oops',billing_period='monthly'), verified)
    assert result is None


def test_research_schema_fields():
    from app.agent_scout import RESEARCH_SCHEMA, VERIFY_SCHEMA, parse_json
    assert 'candidates' in RESEARCH_SCHEMA['required']
    assert 'price_supported' in VERIFY_SCHEMA['required']
    assert parse_json('{"candidates": []}') == {'candidates': []}

def test_malformed_ai_json_is_reported():
    import pytest
    from app.agent_scout import parse_json
    with pytest.raises(ValueError, match='malformed JSON'):
        parse_json('{"candidates": [}')
