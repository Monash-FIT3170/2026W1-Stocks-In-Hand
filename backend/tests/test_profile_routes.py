"""Self-service profile, password-change, and email-change-confirmation routes."""

import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from app.api.deps import get_current_investor
from app.api.routes import auth as auth_routes
from app.core.security import hash_password, hash_session_token, verify_password
from app.crud import investor as investor_crud
from app.database.connection import get_db
from app.models.investor import Investor
from app.services.email_sender import RecordingEmailSender


@pytest.fixture()
def db_session() -> Iterator[Session]:
    # TestClient runs each request in a worker thread, and a bare
    # "sqlite:///:memory:" engine gives every thread its own empty database,
    # so the shared in-memory DB needs one pooled connection all threads reuse.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Investor.__table__.create(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def investor(db_session: Session) -> Investor:
    account = Investor(
        email="profile-test@example.com",
        username="Original Name",
        hashed_password=hash_password("correct-password"),
        role="user",
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture()
def sender(monkeypatch: pytest.MonkeyPatch) -> RecordingEmailSender:
    recording = RecordingEmailSender()
    monkeypatch.setattr(auth_routes, "configured_sender", lambda: recording)
    return recording


@pytest.fixture()
def client(db_session: Session, investor: Investor, sender: RecordingEmailSender) -> Iterator[TestClient]:
    def request_db() -> Iterator[Session]:
        yield db_session

    main.app.dependency_overrides[get_db] = request_db
    main.app.dependency_overrides[get_current_investor] = lambda: investor
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_investor, None)


@pytest.fixture()
def cognito_client(db_session: Session, investor: Investor) -> Iterator[TestClient]:
    investor._authenticated_with_cognito = True

    def request_db() -> Iterator[Session]:
        yield db_session

    main.app.dependency_overrides[get_db] = request_db
    main.app.dependency_overrides[get_current_investor] = lambda: investor
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_investor, None)


def test_update_profile_changes_username_immediately(
    client: TestClient, db_session: Session, investor: Investor
) -> None:
    response = client.patch("/auth/me", json={"username": "New Name"})

    assert response.status_code == 200
    body = response.json()
    assert body["investor"]["username"] == "New Name"
    assert body["investor"]["email"] == "profile-test@example.com"
    db_session.refresh(investor)
    assert investor.username == "New Name"


def test_update_profile_with_new_email_does_not_change_email_immediately(
    client: TestClient, db_session: Session, investor: Investor, sender: RecordingEmailSender
) -> None:
    response = client.patch("/auth/me", json={"email": "new-email@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["investor"]["email"] == "profile-test@example.com"
    assert body["investor"]["pending_email"] == "new-email@example.com"
    assert "confirm" in body["message"].lower()
    db_session.refresh(investor)
    assert investor.email == "profile-test@example.com"
    assert investor.pending_email == "new-email@example.com"
    assert investor.pending_email_token_hash is not None

    assert len(sender.sent) == 1
    assert sender.sent[0].to == "new-email@example.com"


def test_update_profile_rejects_email_already_registered(
    client: TestClient, db_session: Session
) -> None:
    other = Investor(email="taken@example.com", username="Other", role="user")
    db_session.add(other)
    db_session.commit()

    response = client.patch("/auth/me", json={"email": "taken@example.com"})

    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


def test_update_profile_requires_at_least_one_field(client: TestClient) -> None:
    response = client.patch("/auth/me", json={})

    assert response.status_code == 422


def test_change_password_succeeds_with_correct_current_password(
    client: TestClient, db_session: Session, investor: Investor
) -> None:
    response = client.post(
        "/auth/me/change-password",
        json={"current_password": "correct-password", "new_password": "new-password-123"},
    )

    assert response.status_code == 200
    db_session.refresh(investor)
    assert verify_password("new-password-123", investor.hashed_password)
    assert not verify_password("correct-password", investor.hashed_password)


def test_change_password_rejects_wrong_current_password(client: TestClient) -> None:
    response = client.post(
        "/auth/me/change-password",
        json={"current_password": "wrong-password", "new_password": "new-password-123"},
    )

    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"]


def test_update_profile_rejects_cognito_managed_account(cognito_client: TestClient) -> None:
    response = cognito_client.patch("/auth/me", json={"username": "New Name"})

    assert response.status_code == 400
    assert "Cognito" in response.json()["detail"]


def test_change_password_rejects_cognito_managed_account(cognito_client: TestClient) -> None:
    response = cognito_client.post(
        "/auth/me/change-password",
        json={"current_password": "whatever", "new_password": "new-password-123"},
    )

    assert response.status_code == 400
    assert "Cognito" in response.json()["detail"]


def _request_email_change(client: TestClient, sender: RecordingEmailSender, email: str) -> str:
    response = client.patch("/auth/me", json={"email": email})
    assert response.status_code == 200
    link = sender.sent[-1].text
    token = link.split("token=")[1].split("\n")[0].strip()
    return token


def test_confirm_email_change_succeeds_with_valid_token(
    client: TestClient, db_session: Session, investor: Investor, sender: RecordingEmailSender
) -> None:
    token = _request_email_change(client, sender, "new-email@example.com")

    response = client.post("/auth/confirm-email-change", json={"token": token})

    assert response.status_code == 200
    db_session.refresh(investor)
    assert investor.email == "new-email@example.com"
    assert investor.pending_email is None
    assert investor.pending_email_token_hash is None


def test_confirm_email_change_rejects_wrong_token(
    client: TestClient, db_session: Session, investor: Investor, sender: RecordingEmailSender
) -> None:
    _request_email_change(client, sender, "new-email@example.com")
    bad_token = f"{investor.id.hex}.not-the-real-token"

    response = client.post("/auth/confirm-email-change", json={"token": bad_token})

    assert response.status_code == 400
    db_session.refresh(investor)
    assert investor.email == "profile-test@example.com"


def test_confirm_email_change_rejects_expired_token(
    db_session: Session, investor: Investor
) -> None:
    raw_token = "expired-raw-token"
    investor.pending_email = "new-email@example.com"
    investor.pending_email_token_hash = hash_session_token(raw_token)
    investor.pending_email_requested_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db_session.commit()

    with pytest.raises(ValueError, match="invalid or has expired"):
        investor_crud.confirm_email_change(
            db_session, investor.id, raw_token
        )


def test_confirm_email_change_rejects_email_claimed_by_another_account(
    client: TestClient, db_session: Session, investor: Investor, sender: RecordingEmailSender
) -> None:
    token = _request_email_change(client, sender, "new-email@example.com")

    claimant = Investor(email="new-email@example.com", username="Claimant", role="user")
    db_session.add(claimant)
    db_session.commit()

    response = client.post("/auth/confirm-email-change", json={"token": token})

    assert response.status_code == 400
    assert "claimed" in response.json()["detail"]
