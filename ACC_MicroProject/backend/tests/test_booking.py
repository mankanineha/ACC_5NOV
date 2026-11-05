import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, AsyncMock

from backend.app.main import app, seed_database
from backend.app.database import Base, get_db
from backend.app.models import Seat

# Use SQLite in-memory for fast unit testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    seed_database(db)
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_health_endpoint():
    with patch("backend.app.main.get_redis_client") as mock_redis:
        mock_instance = AsyncMock()
        mock_instance.ping.return_value = True
        mock_redis.return_value = mock_instance
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["database_connected"] is True


def test_list_routes():
    response = client.get("/api/routes")
    assert response.status_code == 200
    routes = response.json()
    assert len(routes) >= 2


def test_list_seats():
    with patch("backend.app.main.get_seat_lock_info", new_callable=AsyncMock) as mock_lock_info:
        mock_lock_info.return_value = (False, None, 0)
        response = client.get("/api/shuttles/1/seats")
        assert response.status_code == 200
        seats = response.json()
        assert len(seats) == 24


def test_successful_booking():
    with patch("backend.app.main.acquire_seat_lock", new_callable=AsyncMock) as mock_acquire, \
         patch("backend.app.main.release_seat_lock", new_callable=AsyncMock) as mock_release:
        mock_acquire.return_value = (True, "Locked")
        mock_release.return_value = True

        payload = {
            "seat_id": 1,
            "student_id": "STUDENT-101",
            "student_name": "Alice Sharma"
        }
        response = client.post("/api/book", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["seat_id"] == 1
        assert data["student_id"] == "STUDENT-101"
        assert data["status"] == "CONFIRMED"
        assert "TKT-" in data["booking_reference"]


def test_prevent_double_booking_on_same_seat():
    with patch("backend.app.main.acquire_seat_lock", new_callable=AsyncMock) as mock_acquire, \
         patch("backend.app.main.release_seat_lock", new_callable=AsyncMock) as mock_release:
        mock_acquire.return_value = (True, "Locked")
        mock_release.return_value = True

        # First student books seat 1
        payload1 = {
            "seat_id": 1,
            "student_id": "STUDENT-101",
            "student_name": "Alice Sharma"
        }
        res1 = client.post("/api/book", json=payload1)
        assert res1.status_code == 201

        # Second student attempts to book the exact same seat 1
        payload2 = {
            "seat_id": 1,
            "student_id": "STUDENT-102",
            "student_name": "Bob Verma"
        }
        res2 = client.post("/api/book", json=payload2)
        # Should be rejected with HTTP 409 Conflict!
        assert res2.status_code == 409
        assert "already reserved" in res2.json()["detail"]
