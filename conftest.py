import pytest
from app import limiter


@pytest.fixture(autouse=True, scope="session")
def disable_rate_limiting():
    """Rate limiting is real production behavior, but the test client always
    looks like the same visitor, so without this every test file after the
    first few logins would start tripping the 5/minute login cap. This turns
    the limiter off for the test run only — the real app still enforces it."""
    limiter.enabled = False
