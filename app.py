import os
import base64
import asyncio
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from telethon import TelegramClient, events, types
from telethon.errors import SessionPasswordNeededError, AuthKeyError, AuthKeyUnregisteredError
from get_client import create_telegram_client, validate_client_session, get_session_status

# ================= ENV =================
load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
phone_number = os.getenv("MOBILE_NUM")

DEFAULT_CHANNEL = int(os.getenv("CHANNEL_ID"))
current_channel = DEFAULT_CHANNEL

SESSION_EXPIRES_AT = datetime.now() + timedelta(days=2)  # example

MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

# ================= FastAPI App =================
app = FastAPI(title="Telegram Channel Live Feed API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= Telegram Client =================
try:
    client, client_status = create_telegram_client(api_id, api_hash, phone_number)
    
    print("\n" + "="*60)
    print("Telegram Client Initialization Status:")
    print("="*60)
    print(f"Session Source: {client_status.get('session_source', 'unknown')}")
    print(f"Session Valid: {client_status.get('session_valid', False)}")
    print(f"Requires Login: {client_status.get('requires_login', False)}")
    print(f"Error: {client_status.get('error', 'None')}")
    print("="*60 + "\n")
    
    if client_status.get('error'):
        print(f"⚠️ Warning: {client_status['error']}")
        
except Exception as e:
    print(f"❌ Critical Error creating Telegram client: {e}")
    client = None
# ================= WebSocket Manager =================
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)

    async def send_personal_message(self, data: dict, ws: WebSocket):
        await ws.send_json(data)

    async def broadcast(self, data: dict):
        for ws in self.active_connections:
            try:
                await ws.send_json(data)
            except:
                self.disconnect(ws)

manager = ConnectionManager()

# ================= Utils =================
def safe_text(text: str):
    if not text:
        return ""
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")

def detect_media_type(msg):
    if msg.photo:
        return "photo"
    if msg.video:
        return "video"
    if msg.gif:
        return "gif"
    if msg.voice:
        return "voice"
    if msg.audio:
        return "audio"
    if msg.sticker:
        return "sticker"
    if msg.poll:
        return "poll"
    if msg.document:
        return "file"
    return "text"

def get_mime_type(msg):
    """Get MIME type from message"""
    if msg.file and msg.file.mime_type:
        return msg.file.mime_type
    elif msg.photo:
        return "image/jpeg"
    elif msg.video:
        return "video/mp4"
    elif msg.gif:
        return "image/gif"
    elif msg.voice:
        return "audio/ogg"
    elif msg.audio:
        return "audio/mpeg"
    elif msg.sticker:
        return "image/webp"
    elif msg.document:
        # Try to guess from file extension
        ext = Path(msg.file.name).suffix.lower() if msg.file and msg.file.name else ".bin"
        mime_map = {
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.txt': 'text/plain',
            '.zip': 'application/zip',
            '.rar': 'application/x-rar-compressed',
            '.mp3': 'audio/mpeg',
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
        }
        return mime_map.get(ext, 'application/octet-stream')
    return "application/octet-stream"

async def get_media_data(message_id: int, include_full_data: bool = True) -> Optional[dict]:
    """Download media and return base64 encoded data with metadata"""
    try:
        msg = await client.get_messages(current_channel, ids=message_id)
        
        if not msg or not msg.media:
            return None
        
        media_type = detect_media_type(msg)
        mime_type = get_mime_type(msg)
        
        # For WebSocket real-time, we might want to skip large files
        # or provide a thumbnail instead
        if include_full_data:
            # Download media to bytes
            media_bytes = await client.download_media(msg.media, file=bytes)
            
            if not media_bytes:
                return None
            
            file_size = len(media_bytes)
            media_base64 = base64.b64encode(media_bytes).decode('utf-8')
            
            return {
                "data": media_base64,
                "mime_type": mime_type,
                "file_size": file_size,
                "file_name": f"media_{message_id}{Path(msg.file.name).suffix if msg.file and msg.file.name else ''}",
                "type": media_type
            }
        else:
            # Return only metadata for large files
            file_size = msg.file.size if msg.file else 0
            return {
                "data": None,
                "mime_type": mime_type,
                "file_size": file_size,
                "file_name": f"media_{message_id}{Path(msg.file.name).suffix if msg.file and msg.file.name else ''}",
                "type": media_type,
                "requires_download": True,
                "download_url": f"/media/{message_id}"
            }
        
    except Exception as e:
        print(f"Error getting media data for message {message_id}: {e}")
        return None

def get_today_date():
    """Get today's date in YYYY-MM-DD format"""
    return datetime.now().strftime("%Y-%m-%d")

# ================= Health =================
@app.get("/")
async def home():
    return {"status": "Telegram Channel Live Feed API running 🚀"}

# ================= Session Status Endpoint =================
@app.get("/session-status")
async def get_session_status():
    """
    Check Telegram session authentication status and expiry.
    Returns detailed information about the current session.
    """
    try:
        # Check if client is connected
        is_connected = client.is_connected()
        
        if not is_connected:
            return {
                "status": "disconnected",
                "authenticated": False,
                "is_connected": False,
                "error": "Client is not connected to Telegram servers",
                "requires_reconnect": True
            }
        
        # Try to get "me" to verify authentication
        try:
            me = await client.get_me()
            is_authenticated = bool(me)
            user_info = {
                "id": me.id if me else None,
                "username": me.username if me else None,
                "first_name": me.first_name if me else None,
                "last_name": me.last_name if me else None,
                "phone": me.phone if me else None,
            }
            
            # Get session info
            session_info = client.session.save()
            session_file_path = client.session.filename if hasattr(client.session, 'filename') else None
            
            # Check for any active authorizations
            try:
                # Try to list authorized sessions
                authorized_sessions = await client(GetAuthorizationsRequest())
                session_count = len(authorized_sessions.authorizations) if authorized_sessions else 0
            except:
                session_count = None
            
            return {
                "status": "active",
                "authenticated": is_authenticated,
                "is_connected": is_connected,
                "user": user_info,
                "session_info": {
                    "session_file_exists": os.path.exists(session_file_path) if session_file_path else False,
                    "session_file_path": session_file_path,
                    "session_string": str(session_info)[:100] + "..." if session_info else None,
                },
                "telegram_info": {
                    "current_channel": current_channel,
                    "api_id": api_id,
                    "phone_number": phone_number,
                },
                "timestamp": datetime.now().isoformat(),
                "requires_reconnect": False
            }
            
        except AuthKeyUnregisteredError:
            return {
                "status": "expired",
                "authenticated": False,
                "is_connected": is_connected,
                "error": "Session expired or authorization revoked",
                "requires_reconnect": True,
                "requires_new_login": True,
                "timestamp": datetime.now().isoformat()
            }
            
        except AuthKeyError as e:
            return {
                "status": "auth_error",
                "authenticated": False,
                "is_connected": is_connected,
                "error": f"Authentication key error: {str(e)}",
                "requires_reconnect": True,
                "timestamp": datetime.now().isoformat()
            }
            
        except SessionPasswordNeededError:
            return {
                "status": "password_needed",
                "authenticated": False,
                "is_connected": is_connected,
                "error": "Two-factor authentication required",
                "requires_2fa": True,
                "requires_reconnect": True,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "error",
                "authenticated": False,
                "is_connected": is_connected,
                "error": f"Unknown error checking session: {str(e)}",
                "requires_reconnect": True,
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        return {
            "status": "fatal_error",
            "authenticated": False,
            "is_connected": False,
            "error": f"Fatal error checking session: {str(e)}",
            "requires_reconnect": True,
            "timestamp": datetime.now().isoformat()
        }

# ================= Reconnect Endpoint =================
@app.post("/reconnect")
async def reconnect_session():
    """
    Reconnect the Telegram client session.
    Useful when session expires or connection is lost.
    """
    try:
        # Disconnect if currently connected
        if client.is_connected():
            await client.disconnect()
        
        # Reconnect with the same credentials
        await client.connect()
        
        # Re-authenticate if needed
        if not await client.is_user_authorized():
            await client.send_code_request(phone_number)
            return {
                "status": "code_sent",
                "message": "Authentication code sent to Telegram. Please provide the code.",
                "requires_code": True,
                "timestamp": datetime.now().isoformat()
            }
        
        return {
            "status": "reconnected",
            "message": "Successfully reconnected and authenticated",
            "authenticated": True,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "status": "reconnect_failed",
            "error": f"Failed to reconnect: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }

# ================= Verify Code Endpoint =================
@app.post("/verify-code")
async def verify_code(data: dict):
    """
    Verify authentication code for reconnection.
    Required when 2FA or re-authentication is needed.
    """
    try:
        code = data.get("code")
        password = data.get("password")
        
        if not code:
            raise HTTPException(status_code=400, detail="Code is required")
        
        # Sign in with the code
        await client.sign_in(phone_number, code)
        
        # If password is provided for 2FA
        if password:
            await client.sign_in(password=password)
        
        return {
            "status": "verified",
            "message": "Successfully verified and authenticated",
            "authenticated": True,
            "timestamp": datetime.now().isoformat()
        }
        
    except SessionPasswordNeededError:
        return {
            "status": "password_needed",
            "message": "Two-factor authentication password required",
            "requires_password": True,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "status": "verification_failed",
            "error": f"Failed to verify code: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }

# ================= Messages API =================
@app.get("/messages")
async def get_messages(
    limit: int = 50,
    offset_id: int = 0,
    filter: bool = Query(True, description="If true, only text messages; if false, all messages with media"),
    today_only: bool = Query(False, description="If true, only messages from today")
):
    # Check session status before proceeding
    session_status = await get_session_status()
    if session_status.get("requires_reconnect"):
        raise HTTPException(
            status_code=401, 
            detail=f"Cannot fetch messages: {session_status.get('error', 'Session requires reconnection')}"
        )
    
    messages = await client.get_messages(current_channel, limit=limit, offset_id=offset_id)
    result = []
    
    today = get_today_date()

    for msg in messages:
        # Filter by today if requested
        if today_only and msg.date:
            msg_date = msg.date.strftime("%Y-%m-%d")
            if msg_date != today:
                continue
        
        media_type = detect_media_type(msg)

        # ================= TEXT ONLY MODE =================
        if filter is True:
            if not msg.text:
                continue

            item = {
                "id": msg.id,
                "date": msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else None,
                "date_only": msg.date.strftime("%Y-%m-%d") if msg.date else None,
                "type": "text",
                "text": msg.text,
                "is_today": msg.date.strftime("%Y-%m-%d") == today if msg.date else False
            }

            result.append(item)

        # ================= FULL MEDIA MODE =================
        else:
            item = {
                "id": msg.id,
                "date": msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else None,
                "date_only": msg.date.strftime("%Y-%m-%d") if msg.date else None,
                "type": media_type,
                "text": msg.text or "",
                "has_media": bool(msg.media),
                "is_today": msg.date.strftime("%Y-%m-%d") == today if msg.date else False
            }

            # If media exists, include binary data (limit to 5MB for direct inclusion)
            if msg.media:
                # Check file size - if too large, just provide metadata
                file_size = msg.file.size if msg.file else 0
                include_full = file_size <= 5 * 1024 * 1024  # 5MB limit
                
                media_data = await get_media_data(msg.id, include_full_data=include_full)
                if media_data:
                    item["media_data"] = media_data
                else:
                    item["media_data"] = None
            else:
                item["media_data"] = None

            if msg.poll:
                item["poll"] = {
                    "question": msg.poll.question,
                    "options": [opt.text for opt in msg.poll.answers]
                }

            result.append(item)

    return JSONResponse(result)


# ================= Today's Messages Only =================
@app.get("/messages/today")
async def get_todays_messages(
    limit: int = 100,
    offset_id: int = 0
):
    """Get only today's messages with media"""
    return await get_messages(limit=limit, offset_id=offset_id, filter=False, today_only=True)

# ================= Media Download Endpoint =================
@app.get("/media/{message_id}")
async def get_media(message_id: int, full_data: bool = Query(True, description="Include full base64 data")):
    """Endpoint for direct media download"""
    # Check session status
    session_status = await get_session_status()
    if session_status.get("requires_reconnect"):
        raise HTTPException(
            status_code=401, 
            detail=f"Cannot download media: {session_status.get('error', 'Session requires reconnection')}"
        )
    
    media_data = await get_media_data(message_id, include_full_data=full_data)
    if not media_data:
        raise HTTPException(status_code=404, detail="No media found")
    
    return media_data

# ================= Switch Channel =================
@app.post("/switch-channel")
async def switch_channel(data: dict):
    # Check session status
    session_status = await get_session_status()
    if session_status.get("requires_reconnect"):
        raise HTTPException(
            status_code=401, 
            detail=f"Cannot switch channel: {session_status.get('error', 'Session requires reconnection')}"
        )
    
    global current_channel
    current_channel = int(data["channel_id"])
    return {"status": "ok", "current_channel": current_channel}

# ================= WebSocket =================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Check connection before accepting WebSocket
    try:
        session_status = await get_session_status()
        if session_status.get("requires_reconnect"):
            await ws.accept()
            await ws.send_json({
                "type": "error",
                "error": "Telegram session requires reconnection",
                "session_status": session_status
            })
            await ws.close()
            return
    except:
        pass
    
    await manager.connect(ws)
    try:
        # Send connection confirmation
        await manager.send_personal_message({
            "type": "connection",
            "status": "connected",
            "channel_id": current_channel,
            "date": datetime.now().isoformat()
        }, ws)
        
        # Also send current session status
        session_status = await get_session_status()
        await manager.send_personal_message({
            "type": "session_status",
            "status": session_status
        }, ws)
        
        while True:
            # Keep connection alive
            data = await ws.receive_text()
            if data == "ping":
                await manager.send_personal_message({
                    "type": "pong",
                    "date": datetime.now().isoformat()
                }, ws)
            elif data == "session_status":
                # Client requested session status
                session_status = await get_session_status()
                await manager.send_personal_message({
                    "type": "session_status",
                    "status": session_status
                }, ws)
                
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(ws)

# ================= Telegram Listener =================
@client.on(events.NewMessage)
async def handler(event):
    if event.chat_id != current_channel:
        return

    msg = event.message
    today = get_today_date()
    msg_date = msg.date.strftime("%Y-%m-%d") if msg.date else None
    
    # Only send today's messages via WebSocket
    if msg_date != today:
        return
    
    media_type = detect_media_type(msg)
    has_media = bool(msg.media)
    
    data = {
        "id": msg.id,
        "date": msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else None,
        "date_only": msg_date,
        "type": media_type if has_media else "text",
        "text": msg.text or "",
        "has_media": has_media,
        "is_today": True
    }
    
    # If media exists, try to include it (with size limit for WebSocket)
    if has_media:
        file_size = msg.file.size if msg.file else 0
        include_full = file_size <= 1 * 1024 * 1024  # 1MB limit for WebSocket
        
        media_data = await get_media_data(msg.id, include_full_data=include_full)
        if media_data:
            data["media_data"] = media_data
        else:
            data["media_data"] = None
    
    print(f"📩 Live message: {msg.id} (type: {data['type']})")
    await manager.broadcast(data)

# ================= Startup =================
@app.on_event("startup")
async def startup_event():
    print("🚀 Starting Telegram client...")
    try:
        await client.start(phone=phone_number)
        print("✅ Telegram Connected")
        print(f"📡 Listening to channel: {current_channel}")
        
        # Check and print session status
        session_status = await get_session_status()
        print(f"📊 Session Status: {session_status.get('status', 'unknown')}")
        if session_status.get('authenticated') and session_status.get('user'):
            user = session_status['user']
            print(f"👤 Logged in as: {user.get('first_name', 'Unknown')} (@{user.get('username', 'no_username')})")
    except Exception as e:
        print(f"❌ Failed to start Telegram client: {e}")
        print("⚠️  You may need to reconnect using /reconnect endpoint")

# ================= Shutdown =================
@app.on_event("shutdown")
async def shutdown_event():
    print("🛑 Stopping Telegram client...")
    await client.disconnect()