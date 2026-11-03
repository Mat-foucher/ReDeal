"""Run locally once from backend/: python setup_paypal_plans.py
Creates a sandbox demo product and two billing plans; prints IDs, never secrets.
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
from app.paypal import paypal_call  # noqa: E402


async def main():
    product = await paypal_call('POST', '/v1/catalogs/products', {
        'name': 'ReDealer Demo Membership', 'description': 'Fictional sandbox service for hackathon demonstration',
        'type': 'SERVICE', 'category': 'SOFTWARE'
    })
    print('Product ID:', product['id'])
    for label, amount in [('STANDARD', '25'), ('SAVER', '15')]:
        plan = await paypal_call('POST', '/v1/billing/plans', {
            'product_id': product['id'], 'name': f'ReDealer Demo {label.title()}',
            'description': 'Sandbox-only demo plan', 'status': 'ACTIVE',
            'billing_cycles': [{'frequency': {'interval_unit': 'MONTH', 'interval_count': 1},
                                'tenure_type': 'REGULAR', 'sequence': 1, 'total_cycles': 0,
                                'pricing_scheme': {'fixed_price': {'value': amount, 'currency_code': 'USD'}}}],
            'payment_preferences': {'auto_bill_outstanding': True, 'setup_fee': {'value': '0', 'currency_code': 'USD'},
                                    'setup_fee_failure_action': 'CONTINUE', 'payment_failure_threshold': 3}
        })
        print(f'PAYPAL_{label}_PLAN_ID={plan["id"]}')
    print('Copy the two plan IDs into backend/.env and restart FastAPI.')


if __name__ == '__main__':
    asyncio.run(main())
