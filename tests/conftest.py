"""Authenticated browser helper: sends real CSRF tokens; raw FlaskClient tests cover rejection."""
import os, sys, secrets
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.pop('DATABASE_URL', None)
os.environ.pop('FLASK_ENV', None)
os.environ.pop('RENDER', None)
import app as A
from flask.testing import FlaskClient
class BrowserClient(FlaskClient):
    def post(self, *args, **kwargs):
        with self.session_transaction() as s:
            token = s.setdefault('csrf_token', secrets.token_urlsafe(32))
        kwargs['headers'] = {**kwargs.get('headers', {}), 'X-CSRF-Token': token}
        return super().post(*args, **kwargs)
A.app.test_client_class = BrowserClient
