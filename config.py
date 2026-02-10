import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") 
DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "yachejka_bot")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]

# === ID ВЕТКИ С АНОНСАМИ ===
# Впишите сюда ID топика (например, 2 или 349332). 
# Если у вас отдельный КАНАЛ, впишите сюда ID канала (обычно начинается с -100...)
ANNOUNCEMENT_THREAD_ID = 3  # <-- ЗАМЕНИТЕ НА ВАШ РЕАЛЬНЫЙ ID

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("❌ Не заданы TELEGRAM_TOKEN или OPENROUTER_API_KEY")
