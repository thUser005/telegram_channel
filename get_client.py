# get_client.py
import os
import base64
import logging
from typing import Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta

from telethon import TelegramClient
from telethon.sessions import MemorySession, SQLiteSession
from telethon.errors import (
    SessionPasswordNeededError,
    AuthKeyError,
    AuthKeyUnregisteredError,
    AuthKeyDuplicatedError,
    SessionExpiredError
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_session_from_string(session_string: str) -> Optional[MemorySession]:
    """Load session from base64 encoded string"""
    try:
        # Decode base64 session string
        session_data = base64.b64decode(session_string)
        
        # Create MemorySession from bytes
        session = MemorySession(session_data)
        
        # Validate session by checking if it has required attributes
        if hasattr(session, '_auth_key') and session._auth_key:
            logger.info("✅ Session loaded successfully from string")
            return session
        else:
            logger.warning("⚠️ Session string loaded but appears empty or invalid")
            return None
            
    except (base64.binascii.Error, ValueError) as e:
        logger.error(f"❌ Invalid base64 session string: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error loading session from string: {e}")
        return None

def check_session_file_health(session_file_path: str) -> Tuple[bool, str]:
    """Check if session file is valid and not corrupted"""
    try:
        path = Path(session_file_path)
        
        # Check if file exists
        if not path.exists():
            return False, "Session file does not exist"
        
        # Check file size (should be reasonable for a session file)
        file_size = path.stat().st_size
        if file_size < 100:  # Too small to be valid
            return False, f"Session file too small ({file_size} bytes)"
        if file_size > 10 * 1024 * 1024:  # Too large
            return False, f"Session file too large ({file_size} bytes)"
        
        # Try to load it with SQLiteSession to validate
        try:
            # This is a basic check - Telethon will do proper validation later
            with open(session_file_path, 'rb') as f:
                header = f.read(100)
                if not header:
                    return False, "Empty session file"
            
            logger.info(f"✅ Session file appears valid ({file_size} bytes)")
            return True, "Session file appears valid"
            
        except Exception as e:
            return False, f"Error reading session file: {e}"
            
    except Exception as e:
        return False, f"Error checking session file: {e}"

def create_telegram_client(api_id: int, api_hash: str, phone_number: str = None) -> Tuple[TelegramClient, dict]:
    """
    Create Telegram client with comprehensive session handling
    
    Returns:
        Tuple[TelegramClient, dict]: Client instance and status information
    """
    status_info = {
        "session_source": None,
        "session_valid": False,
        "error": None,
        "requires_login": False,
        "requires_2fa": False,
        "expired": False
    }
    
    client = None
    session = None
    
    # Priority 1: Try SESSION_STRING from environment
    session_string = os.getenv("SESSION_STRING")
    if session_string:
        try:
            logger.info("🔄 Attempting to load session from SESSION_STRING")
            session = load_session_from_string(session_string)
            
            if session:
                client = TelegramClient(session, api_id, api_hash)
                status_info["session_source"] = "environment_string"
                status_info["session_valid"] = True
                logger.info("✅ Created client from SESSION_STRING")
                return client, status_info
            else:
                logger.warning("⚠️ SESSION_STRING found but failed to load")
                status_info["error"] = "Failed to load session from SESSION_STRING"
                
        except Exception as e:
            logger.error(f"❌ Error creating client from SESSION_STRING: {e}")
            status_info["error"] = f"Error creating from SESSION_STRING: {str(e)}"
    
    # Priority 2: Try session file
    session_file_paths = [
        "session_name.session",
        "session.session",
        "telegram.session"
    ]
    
    for session_file in session_file_paths:
        if os.path.exists(session_file):
            try:
                logger.info(f"🔄 Attempting to load session from file: {session_file}")
                
                # Check file health
                is_valid, message = check_session_file_health(session_file)
                
                if is_valid:
                    client = TelegramClient(session_file, api_id, api_hash)
                    status_info["session_source"] = f"file:{session_file}"
                    status_info["session_valid"] = True
                    logger.info(f"✅ Created client from session file: {session_file}")
                    return client, status_info
                else:
                    logger.warning(f"⚠️ Session file {session_file} appears invalid: {message}")
                    status_info["error"] = f"Invalid session file: {message}"
                    
            except Exception as e:
                logger.error(f"❌ Error creating client from file {session_file}: {e}")
                status_info["error"] = f"Error loading {session_file}: {str(e)}"
    
    # Priority 3: Create new client (requires login)
    logger.info("🔄 No valid session found. Creating new client (requires login)")
    try:
        # Use a temporary session name that won't conflict
        temp_session_name = f"temp_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        client = TelegramClient(temp_session_name, api_id, api_hash)
        
        status_info["session_source"] = "new"
        status_info["requires_login"] = True
        status_info["session_valid"] = False
        logger.info("✅ Created new client instance (login required)")
        
        return client, status_info
        
    except Exception as e:
        logger.error(f"❌ Failed to create Telegram client: {e}")
        status_info["error"] = f"Failed to create client: {str(e)}"
        raise RuntimeError(f"Failed to create Telegram client: {e}")

def validate_client_session(client: TelegramClient) -> Tuple[bool, dict]:
    """
    Validate if the client's session is still active and authorized
    
    Returns:
        Tuple[bool, dict]: (is_valid, validation_info)
    """
    validation_info = {
        "is_connected": False,
        "is_authorized": False,
        "is_expired": False,
        "requires_2fa": False,
        "user_info": None,
        "error": None
    }
    
    try:
        # Check connection
        if client.is_connected():
            validation_info["is_connected"] = True
            
            # Check authorization
            if client._sender is not None and hasattr(client._sender, '_auth_key'):
                # Try to get user info (this will fail if session is invalid)
                try:
                    # We'll do actual validation when we try to use it
                    validation_info["is_authorized"] = True
                    logger.info("✅ Client appears to be connected and authorized")
                    
                except (AuthKeyUnregisteredError, AuthKeyError, SessionExpiredError) as e:
                    validation_info["is_expired"] = True
                    validation_info["error"] = f"Session expired: {e}"
                    logger.warning(f"⚠️ Session appears expired: {e}")
                    
                except Exception as e:
                    validation_info["error"] = f"Validation error: {e}"
                    logger.error(f"❌ Error validating session: {e}")
            else:
                validation_info["error"] = "No auth key found in session"
                logger.warning("⚠️ No auth key found in session")
                
        else:
            validation_info["error"] = "Client not connected"
            logger.warning("⚠️ Client is not connected")
            
    except Exception as e:
        validation_info["error"] = f"Exception during validation: {e}"
        logger.error(f"❌ Exception during session validation: {e}")
    
    return validation_info["is_connected"] and validation_info["is_authorized"], validation_info

def get_session_status(client: TelegramClient) -> dict:
    """Get detailed session status"""
    try:
        # Basic connection check
        is_connected = client.is_connected()
        
        # Try to get user info to verify session
        try:
            if is_connected:
                # This will raise an exception if session is invalid
                me = client.loop.run_until_complete(client.get_me())
                
                return {
                    "status": "active",
                    "authenticated": True,
                    "is_connected": True,
                    "user": {
                        "id": me.id if me else None,
                        "username": me.username if me else None,
                        "first_name": me.first_name if me else None,
                        "last_name": me.last_name if me else None,
                        "phone": me.phone if me else None,
                    },
                    "session_file": client.session.filename if hasattr(client.session, 'filename') else "memory_session",
                    "timestamp": datetime.now().isoformat(),
                    "requires_reconnect": False,
                    "error": None
                }
            else:
                return {
                    "status": "disconnected",
                    "authenticated": False,
                    "is_connected": False,
                    "error": "Client is not connected",
                    "requires_reconnect": True,
                    "timestamp": datetime.now().isoformat()
                }
                
        except (AuthKeyUnregisteredError, AuthKeyError, SessionExpiredError) as e:
            return {
                "status": "expired",
                "authenticated": False,
                "is_connected": is_connected,
                "error": f"Session expired: {e}",
                "requires_reconnect": True,
                "requires_new_login": True,
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
                "error": f"Error checking session: {str(e)}",
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