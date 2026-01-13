from telethon import TelegramClient
import os
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")

client = TelegramClient("session_name.session", api_id, api_hash)

async def main():
    await client.start()
    msgs = await client.get_messages(2560862430, limit=100)
    print("Total fetched:", len(msgs))

    for m in msgs:
        print(m.id, m.text[:50] if m.text else "NO TEXT")

with client:
    client.loop.run_until_complete(main())
