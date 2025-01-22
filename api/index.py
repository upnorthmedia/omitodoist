from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import aiohttp
import asyncio
from typing import Dict, Optional, List
from datetime import datetime
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import uuid
from pathlib import Path
from . import db

# Load environment variables
load_dotenv()

app = FastAPI(title="Todoist Voice Task Plugin")

# Update templates directory path
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Models based on Omi's memory creation payload
class TranscriptSegment(BaseModel):
    text: str
    speaker: str
    speaker_id: int
    is_user: bool
    start: float
    end: float
    person_id: Optional[str] = None

class Event(BaseModel):
    title: str
    description: str
    start: str
    duration: int
    created: bool

class ActionItem(BaseModel):
    description: str
    completed: bool
    deleted: bool = False

class StructuredData(BaseModel):
    title: str
    overview: str
    emoji: str
    category: str
    action_items: List[ActionItem]
    events: List[Event]

class MemoryPayload(BaseModel):
    id: str
    created_at: datetime
    started_at: datetime
    finished_at: datetime
    source: str
    language: str
    structured: StructuredData
    transcript_segments: List[TranscriptSegment]
    geolocation: Optional[Dict] = None
    photos: List[str]
    plugins_results: List[Dict] = []
    external_data: Optional[Dict] = None
    discarded: bool
    deleted: bool = False
    visibility: str
    processing_memory_id: Optional[str] = None
    status: str

async def create_todoist_task(api_key: str, content: str, retries: int = 3) -> Dict:
    """Create a task in Todoist with retry logic"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Request-Id": str(uuid.uuid4())  # Add idempotency key
    }
    
    url = "https://api.todoist.com/rest/v2/tasks"
    payload = {
        "content": content,
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
                    print(f"Todoist API response: {response.status} - {response_text}")
                    
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
        # Debug logging
        print("Received webhook request")
        
        user_id = request.query_params.get("uid")
        print(f"User ID: {user_id}")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="Missing user ID")

        # Get API key from database
        api_key = db.get_api_key(user_id)
        print(f"API Key found: {bool(api_key)}")
        
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="Todoist API key not configured. Please set up your Todoist integration first."
            )

        # Debug log request body
        body = await request.json()
        print(f"Request body: {body}")
        
        try:
            memory_data = MemoryPayload.parse_obj(body)
            print("Successfully parsed memory payload")
        except Exception as e:
            print(f"Failed to parse memory payload: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid memory payload: {str(e)}"
            )
        
        tasks = []
        
        # Extract tasks from structured action items only
        print(f"Found {len(memory_data.structured.action_items)} action items")
        for action_item in memory_data.structured.action_items:
            if not action_item.completed and not action_item.deleted:
                sanitized_text = sanitize_text(action_item.description)
                print(f"Creating task: {sanitized_text}")
                try:
                    task = await create_todoist_task(api_key, sanitized_text)
                    tasks.append(task)
                    print(f"Successfully created task: {task}")
                except Exception as e:
                    print(f"Failed to create task: {str(e)}")
                    continue

        print(f"Successfully created {len(tasks)} tasks")
        return {
            "status": "success",
            "tasks_created": len(tasks),
            "tasks": tasks
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Show setup form"""
    uid = request.query_params.get("uid")
    if not uid:
        raise HTTPException(status_code=400, detail="Missing user ID")
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
        success = db.store_api_key(uid, api_key)
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