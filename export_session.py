# export_session.py
import os
import base64
import json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

def export_session():
    """Export session to base64 string for Railway"""
    
    session_files = ["session_name.session", "session.session", "telegram.session"]
    session_found = False
    
    for session_file in session_files:
        if os.path.exists(session_file):
            try:
                print(f"📁 Found session file: {session_file}")
                
                # Read session file
                with open(session_file, "rb") as f:
                    session_data = f.read()
                
                # Convert to base64 string
                session_string = base64.b64encode(session_data).decode('utf-8')
                
                # Calculate size
                original_size = len(session_data)
                encoded_size = len(session_string)
                
                print("\n" + "="*70)
                print("SESSION_STRING for Railway Environment Variable:")
                print("="*70)
                print(session_string)
                print("="*70)
                print(f"\n📊 Session Details:")
                print(f"  File: {session_file}")
                print(f"  Original size: {original_size:,} bytes")
                print(f"  Base64 size: {encoded_size:,} characters")
                print(f"  Increase: {((encoded_size/original_size)-1)*100:.1f}%")
                
                # Save to files
                with open("session_base64.txt", "w") as f:
                    f.write(session_string)
                
                # Create .env.example with instructions
                env_example = """# Copy this to Railway environment variables
SESSION_STRING={}
API_ID={}
API_HASH={}
MOBILE_NUM={}
""".format(
    session_string[:100] + "..." if len(session_string) > 100 else session_string,
    os.getenv("API_ID", "YOUR_API_ID"),
    os.getenv("API_HASH", "YOUR_API_HASH"),
    os.getenv("MOBILE_NUM", "YOUR_PHONE_NUMBER")
)
                
                with open(".env.example", "w") as f:
                    f.write(env_example)
                
                print("\n✅ Files created:")
                print(f"  - session_base64.txt (full session string)")
                print(f"  - .env.example (template for Railway)")
                
                print("\n📋 Instructions for Railway:")
                print("  1. Go to Railway dashboard → Variables")
                print("  2. Add SESSION_STRING variable")
                print("  3. Paste the entire string above")
                print("  4. Also add API_ID, API_HASH, MOBILE_NUM")
                
                session_found = True
                break
                
            except Exception as e:
                print(f"❌ Error reading {session_file}: {e}")
    
    if not session_found:
        print("❌ No session file found!")
        print("Available session files to check:")
        for session_file in session_files:
            if not os.path.exists(session_file):
                print(f"  - {session_file} (not found)")
        
        print("\n💡 To create a session file:")
        print("  1. Run your app locally first")
        print("  2. Complete Telegram authentication")
        print("  3. Then run this script again")

def import_session_string():
    """Test importing a session string back to file"""
    session_string = os.getenv("SESSION_STRING")
    
    if session_string:
        try:
            # Decode back to bytes
            session_data = base64.b64decode(session_string)
            
            # Save to file
            test_file = "test_import.session"
            with open(test_file, "wb") as f:
                f.write(session_data)
            
            print(f"\n✅ Import test successful!")
            print(f"  Saved to: {test_file}")
            print(f"  File size: {len(session_data):,} bytes")
            
            return True
            
        except Exception as e:
            print(f"❌ Import test failed: {e}")
            return False
    else:
        print("⚠️ No SESSION_STRING in environment to test import")
        return False

if __name__ == "__main__":
    print("🔐 Telegram Session Exporter")
    print("="*50)
    
    export_session()
    
    print("\n" + "="*50)
    print("🔄 Testing session import (optional)...")
    import_session_string()