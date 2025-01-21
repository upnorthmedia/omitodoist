from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse
import aiohttp
import asyncio
from typing import Dict, Optional, List
from datetime import datetime
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import uuid
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Load environment variables
load_dotenv()

# Mock Omi SDK with local storage fallback
class OmiClient:
    class KVStore:
        async def get(self, key: str) -> Optional[str]:
            # For local testing, use environment variables
            if os.getenv("LOCAL_TESTING"):
                return os.getenv(key)
            # In production, this would interact with Omi's actual KV store
            return None
            
        async def set(self, key: str, value: str) -> bool:
            # For local testing, store in environment
            if os.getenv("LOCAL_TESTING"):
                os.environ[key] = value
                return True
            # In production, this would interact with Omi's actual KV store
            return True

    def __init__(self):
        self.kv = self.KVStore()

app = FastAPI(title="Todoist Voice Task Plugin")

# Update the templates directory path to work with Vercel
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Add this near the top of main.py, after creating the FastAPI app
app.mount("/static", StaticFiles(directory="static"), name="static")

# Models based on Omi's memory creation payload
class TranscriptSegment(BaseModel):
    text: str
    speaker: str
    speakerId: int
    is_user: bool
    start: float
    end: float

class ActionItem(BaseModel):
    description: str
    completed: bool

class StructuredData(BaseModel):
    title: str
    overview: str
    emoji: str
    category: str
    action_items: List[ActionItem]
    events: List[Dict]

class AppResponse(BaseModel):
    app_id: str
    content: str

class MemoryPayload(BaseModel):
    id: int
    created_at: datetime
    started_at: datetime
    finished_at: datetime
    transcript_segments: List[TranscriptSegment]
    photos: List[str]
    structured: StructuredData
    apps_response: List[AppResponse]
    discarded: bool

class TodoistKeyPayload(BaseModel):
    user_id: str
    api_key: str

async def get_todoist_key(user_id: str) -> Optional[str]:
    """Get Todoist API key from Omi's KV store"""
    try:
        omi_client = OmiClient()
        key = await omi_client.kv.get(f"todoist_key_{user_id}")
        return key
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve API key: {str(e)}"
        )

async def store_todoist_key(user_id: str, api_key: str) -> bool:
    """Store Todoist API key in Omi's KV store"""
    try:
        omi_client = OmiClient()
        await omi_client.kv.set(f"todoist_key_{user_id}", api_key)
        return True
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store API key: {str(e)}"
        )

async def create_todoist_task(api_key: str, content: str, retries: int = 3) -> Dict:
    """Create a task in Todoist with retry logic"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Request-Id": str(uuid.uuid4())  # Add idempotency key
    }
    
    # Use Todoist's REST API v2 endpoint
    url = "https://api.todoist.com/rest/v2/tasks"
    payload = {
        "content": content,
        "due_string": "today",  # Add default due date
        "priority": 1,
        "project_id": None  # None means it will go to Inbox
    }
    
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers
                ) as response:
                    response_text = await response.text()
                    print(f"Todoist API response: {response.status} - {response_text}")  # Debug line
                    
                    if response.status == 200:
                        return await response.json()
                    if response.status not in {429, 502, 503} or attempt == retries - 1:
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"Todoist API error: {response_text}"
                        )
        except aiohttp.ClientError as e:
            if attempt == retries - 1:
                raise HTTPException(status_code=500, detail=str(e))
        await asyncio.sleep(2 ** attempt)

def sanitize_text(text: str, max_length: int = 500) -> str:
    """Sanitize and truncate input text"""
    sanitized = text.replace("<", "&lt;").replace(">", "&gt;")
    return sanitized[:max_length]

@app.post("/webhook")
async def handle_memory_creation(request: Request):
    """Handle memory creation webhook from Omi"""
    try:
        # Get user ID from query parameters as specified in Omi docs
        user_id = request.query_params.get("uid")
        if not user_id:
            raise HTTPException(status_code=400, detail="Missing user ID")

        # Get API key from Omi's KV store
        api_key = await get_todoist_key(user_id)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="Todoist API key not configured. Please set up your Todoist integration first."
            )

        # Parse the memory payload
        memory_data = MemoryPayload.parse_obj(await request.json())
        
        # Create tasks for each action item in the structured data
        tasks = []
        for action_item in memory_data.structured.action_items:
            if not action_item.completed:  # Only create tasks for incomplete action items
                sanitized_text = sanitize_text(action_item.description)
                task = await create_todoist_task(api_key, sanitized_text)
                tasks.append(task)

        return {
            "status": "success",
            "tasks_created": len(tasks),
            "tasks": tasks
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Show setup form"""
    uid = request.query_params.get("uid")
    return templates.TemplateResponse(
        "setup.html",
        {"request": request, "uid": uid}
    )

@app.post("/setup")
async def setup_todoist(request: Request, api_key: str = Form(...), uid: str = Form(...)):
    """Handle setup form submission"""
    try:
        # Validate the API key with Todoist before storing
        test_response = await create_todoist_task(
            api_key,
            "Test task - please ignore",
            retries=1
        )
        
        # If we get here, the API key is valid
        success = await store_todoist_key(uid, api_key)
        if success:
            return templates.TemplateResponse(
                "setup_success.html",
                {"request": request}
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to store API key"
            )
    except Exception as e:
        return templates.TemplateResponse(
            "setup.html",
            {
                "request": request,
                "uid": uid,
                "error": str(e)
            }
        )

@app.get("/setup-done")
async def setup_complete():
    """Check if setup is completed"""
    return {"is_setup_completed": True}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Todoist Integration API"} 