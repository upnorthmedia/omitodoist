import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from main import app
from datetime import datetime, timezone
import os
import asyncio

# Set up local testing environment
os.environ["LOCAL_TESTING"] = "true"
os.environ["TODOIST_API_KEY"] = "d5ac866e69ae82890339f307ee69c6814e3ab0a1"

# Create a new event loop for each test
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

client = TestClient(app)

# Mock Omi client for testing
class MockOmiClient:
    def __init__(self):
        self.kv = AsyncMock()
        # Set default return values
        self.kv.get.return_value = "test_api_key"
        self.kv.set.return_value = True

@pytest.fixture
def mock_omi():  # Remove async
    mock = MockOmiClient()
    with patch('main.OmiClient', return_value=mock):
        yield mock

@pytest.fixture
def memory_payload():
    # Match exactly the format from Omi docs
    return {
        "id": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "transcript_segments": [
            {
                "text": "Remember to buy milk",
                "speaker": "SPEAKER_00",
                "speakerId": 0,
                "is_user": False,
                "start": 10.0,
                "end": 20.0
            }
        ],
        "photos": [],
        "structured": {
            "title": "Shopping List Discussion",
            "overview": "Brief overview...",
            "emoji": "🗣️",
            "category": "personal",
            "action_items": [
                {
                    "description": "Buy milk",
                    "completed": False
                }
            ],
            "events": []
        },
        "apps_response": [
            {
                "app_id": "todoist",
                "content": "Task created"
            }
        ],
        "discarded": False
    }

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_setup_complete():
    response = client.get("/setup-done")
    assert response.status_code == 200
    assert response.json() == {"is_setup_completed": True}

@pytest.mark.asyncio
async def test_webhook_with_memory(mock_omi, memory_payload):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Mock Todoist API response
        async def mock_create_task(*args, **kwargs):
            return {
                "id": "123",
                "content": "Buy milk",
                "completed": False,
                "url": "https://todoist.com/showTask?id=123",
                "created_at": "2024-03-14T12:00:00Z"
            }
        
        with patch('main.create_todoist_task', side_effect=mock_create_task):
            response = await ac.post(
                "/webhook?uid=test123",
                json=memory_payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Response: {response.status_code}")  # Debug line
            print(f"Response body: {response.json()}")  # Debug line
            
            assert response.status_code == 200
            assert response.json()["status"] == "success"
            assert response.json()["tasks_created"] == 1

@pytest.mark.asyncio
async def test_setup_todoist(mock_omi):
    payload = {"user_id": "test123", "api_key": "fake_api_key"}
    async with AsyncClient(app=app, base_url="http://test") as ac:
        async def mock_create_task(*args, **kwargs):
            return {"id": "123"}
            
        with patch('main.create_todoist_task', side_effect=mock_create_task):
            response = await ac.post("/setup", json=payload)
            assert response.status_code == 200
            assert response.json()["status"] == "success"

def test_webhook_missing_uid():
    response = client.post("/webhook", json={})
    assert response.status_code == 400
    assert "Missing user ID" in response.json()["detail"]

# Add more tests as needed... 