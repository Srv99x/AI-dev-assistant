"""
Tests for weekly digest scheduler.
Run: cd backend && pytest tests/test_scheduler.py -v
"""

import os
import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import Base
from app.models import DigestSubscription
from app.services import scheduler as scheduler_service

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# In-memory SQLite for fast, isolated testing
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TEST_SESSION_LOCAL = sessionmaker(bind=TEST_ENGINE)

@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Put the system in a clean known state before each test."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    monkeypatch.setattr(scheduler_service, "SessionLocal", TEST_SESSION_LOCAL)

    # Clean out any scheduled jobs
    for job in scheduler_service.scheduler.get_jobs():
        job.remove()

    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


def test_send_weekly_digests_disabled(monkeypatch):
    """When digest_enabled is False, it returns early without touching DB."""
    monkeypatch.setattr(scheduler_service.settings, "digest_enabled", False)

    mock_session = MagicMock()
    monkeypatch.setattr(scheduler_service, "SessionLocal", mock_session)

    scheduler_service._send_weekly_digests()
    mock_session.assert_not_called()

def test_send_weekly_digests_no_subscribers(monkeypatch):
    """When there are zero active subscribers, it exits gracefully."""
    monkeypatch.setattr(scheduler_service.settings, "digest_enabled", True)

    mock_compute = MagicMock()
    monkeypatch.setattr(scheduler_service, "compute_subscriber_stats", mock_compute)

    scheduler_service._send_weekly_digests()
    mock_compute.assert_not_called()

def test_send_weekly_digests_success(monkeypatch):
    """When send_digest returns True, last_sent_at is updated."""
    monkeypatch.setattr(scheduler_service.settings, "digest_enabled", True)

    db = TEST_SESSION_LOCAL()
    sub = DigestSubscription(email="test@example.com", is_active=True, unsubscribe_token="token")
    db.add(sub)
    db.commit()

    mock_compute = MagicMock(return_value={"stats": "data"})
    mock_send = MagicMock(return_value=True)
    monkeypatch.setattr(scheduler_service, "compute_subscriber_stats", mock_compute)
    monkeypatch.setattr(scheduler_service, "send_digest", mock_send)

    scheduler_service._send_weekly_digests()

    db.refresh(sub)
    assert sub.last_sent_at is not None
    from unittest.mock import ANY
    mock_compute.assert_called_once_with(ANY, "test@example.com")
    mock_send.assert_called_once_with({"stats": "data"}, "token")

def test_send_weekly_digests_failure_does_not_update_last_sent_at(monkeypatch):
    """When send_digest returns False, last_sent_at is NOT updated."""
    monkeypatch.setattr(scheduler_service.settings, "digest_enabled", True)

    db = TEST_SESSION_LOCAL()
    sub = DigestSubscription(email="fail@example.com", is_active=True, unsubscribe_token="token2")
    db.add(sub)
    db.commit()

    mock_compute = MagicMock(return_value={"stats": "data"})
    mock_send = MagicMock(return_value=False)
    monkeypatch.setattr(scheduler_service, "compute_subscriber_stats", mock_compute)
    monkeypatch.setattr(scheduler_service, "send_digest", mock_send)

    scheduler_service._send_weekly_digests()

    db.refresh(sub)
    assert sub.last_sent_at is None

def test_start_scheduler_adds_job():
    """Does start_scheduler() add a job with the correct JOB_ID?"""
    scheduler_service.start_scheduler()
    job = scheduler_service.scheduler.get_job(scheduler_service.JOB_ID)
    assert job is not None
    assert job.id == scheduler_service.JOB_ID

def test_start_scheduler_twice_prevents_duplicate_jobs():
    """Does calling start_scheduler() twice avoid adding duplicate jobs?"""
    try:
        scheduler_service.start_scheduler()
    except Exception:
        pass
    try:
        scheduler_service.start_scheduler()
    except Exception:
        pass

    jobs = scheduler_service.scheduler.get_jobs()
    digest_jobs = [j for j in jobs if j.id == scheduler_service.JOB_ID]
    assert len(digest_jobs) == 1