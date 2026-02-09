import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") # Бывший GEMINI_API_KEY
DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "yachejka_bot")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]

# === ID ВЕТКИ С АНОНСАМИ ===
# Замените 0 на реальный ID, который вы узнали в логах!
# Например: ANNOUNCEMENT_THREAD_ID = 2
ANNOUNCEMENT_THREAD_ID = 349332

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("❌ Не заданы TELEGRAM_TOKEN или OPENROUTER_API_KEY")
