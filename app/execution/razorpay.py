import time
import requests
from requests.auth import HTTPBasicAuth
from app.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

class RazorpayAPIError(RuntimeError):
    pass

class RazorpayAdapter:
    BASE = 'https://api.razorpay.com/v1'
    def __init__(self, key_id=RAZORPAY_KEY_ID, key_secret=RAZORPAY_KEY_SECRET, timeout=10, max_retries=2):
        self.key_id, self.key_secret = key_id, key_secret
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def _auth(self):
        if not self.key_id or not self.key_secret:
            raise RazorpayAPIError('Razorpay test credentials are not configured')
        return HTTPBasicAuth(self.key_id, self.key_secret)

    def _request(self, method, path, **kwargs):
        kwargs.setdefault('timeout', self.timeout)
        kwargs['auth'] = self._auth()
        last = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, f'{self.BASE}{path}', **kwargs)
                if response.status_code >= 500 and attempt < self.max_retries:
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last = exc
                if attempt >= self.max_retries:
                    raise RazorpayAPIError(str(exc)) from exc
                time.sleep(0.25 * (2 ** attempt))
        raise RazorpayAPIError(str(last))

    def create_plan(self, name, amount_paise, period='monthly', interval=1):
        return self._request('POST', '/plans', json={'period': period, 'interval': interval, 'item': {'name': name, 'amount': amount_paise, 'currency': 'INR', 'description': name}})

    def create_subscription(self, plan_id, total_count=6, quantity=1, start_at=None):
        payload = {'plan_id': plan_id, 'total_count': total_count, 'quantity': quantity, 'customer_notify': True}
        if start_at is not None: payload['start_at'] = start_at
        return self._request('POST', '/subscriptions', json=payload)

    def fetch_subscription(self, subscription_id):
        return self._request('GET', f'/subscriptions/{subscription_id}')

    def fetch_subscription_invoices(self, subscription_id):
        return self._request('GET', '/invoices', params={'subscription_id': subscription_id})

    def fetch_invoice(self, invoice_id):
        return self._request('GET', f'/invoices/{invoice_id}')
