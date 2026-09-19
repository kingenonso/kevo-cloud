"""
Tests for the Liquidity Friction Indicator (first slice) - written against
the REAL ~/KEVO implementation (2026-09-19).

Packages M14's evaluate_transferability() and M15's build_liquidity_path()
into an explained illiquidity-friction readout for a listing. Nothing new
is computed or persisted here - this wraps two already-tested, already-real
engines. These tests focus on the new packaging logic itself: the
determinability breakdown, the main_constraint priority ordering (blocked
transferability > unresolved ROFR > other transferability issues > earliest
unresolved liquidity-path step), and that nothing is persisted.

Runs against an isolated in-memory SQLite database, same pattern as
test_m14.py / test_m15.py / test_m17.py - does not touch the real Postgres
config.
"""

import os

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import itertools
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base,
    User as UserModel,
    Listing as ListingModel,
    OwnershipRecord,
    TransferabilityRule,
    TransferabilityFact,
    LiquidityPathStep,
)
from app import app, get_db, hash_password, create_access_token

_email_counter = itertools.count(1)
