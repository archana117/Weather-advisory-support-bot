import pytest
from starlette.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["loaded_sops"] >= 10

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["sop_count"] >= 10

def test_list_sops_endpoint(client):
    response = client.get("/sops")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 10
    assert len(data["sops"]) >= 10

def test_chat_endpoint_valid(client):
    response = client.post("/chat", json={
        "message": "Is it safe to cycle in Bhopal today?",
        "session_id": "test_api_sess"
    })
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert data["status"] in ["success", "advisory_issued", "no_sop"]

def test_chat_endpoint_empty_message(client):
    response = client.post("/chat", json={
        "message": "   ",
        "session_id": "test_api_empty"
    })
    assert response.status_code == 400
    assert "Message cannot be empty" in response.json()["detail"]
