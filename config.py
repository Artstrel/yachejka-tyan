import os
from dotenv import load_dotenv

load_dotenv()

# API Keys - теперь берем из окружения (Secrets)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "yachejka_bot")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("❌ Не заданы TELEGRAM_TOKEN или GEMINI_API_KEY")