import motor.motor_asyncio
from datetime import datetime, timedelta
import logging
import re
import config

class Database:
    def __init__(self, uri, db_name="yachejka_bot"):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self.client[db_name]
        self.messages = self.db.messages
        self.stickers = self.db.stickers

    async def connect(self):
        try:
            await self.client.admin.command('ping')
            logging.info("✅ MongoDB Connected")
        except Exception as e:
            logging.error(f"❌ MongoDB Error: {e}")

    async def add_message(self, chat_id, user_id, user_name, role, content, thread_id=None):
        await self.messages.insert_one({
            "chat_id": chat_id,
            "message_thread_id": thread_id,
            "user_id": user_id,
            "user_name": user_name,
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow()
        })

    async def get_context(self, chat_id, limit=10):
        # Это для обычного диалога (последние 10 сообщений)
        cursor = self.messages.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        return history[::-1]

    # --- УМНЫЙ ПОИСК АНОНСОВ ---
    async def get_potential_announcements(self, chat_id, days=21, limit=10):
        # Ищем сообщения за последние 21 день
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # КЛЮЧЕВЫЕ СЛОВА (Regex)
        # Мы ищем любые сообщения, где есть упоминание времени, места ИЛИ активности.
        keywords = [
            # 1. Активности и контент
            "аниме", "anime", "тайтл", "title", "серия", "эпизод", "сезон", 
            "онгоинг", "премьера", "показ", "screen", "watch", "смотрим", "просмотр",
            "кино", "фильм", "мульт", "презентаци", "powerpoint", "квиз", "quiz",
            "мафия", "mafia", "настол", "играем", "игра", "башн", "clocktower",
            
            # 2. Локации (твои частые места)
            "d22", "red&wine", "red & wine", "coffee lars", "amaghleba", "tabukashvili",
            "бар", "bar", "место:", "адрес",
            
            # 3. Время и дни (самый надежный маркер)
            r"\d{1,2}:\d{2}",  # Время типа 19:00
            "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
            "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря",
            "завтра", "сегодня"
        ]
        
        regex_pattern = "|".join(keywords)

        query = {
            "chat_id": chat_id,
            # Игнорируем сообщения от самого бота (role != model), чтобы он не читал свои же анонсы
            "role": "user", 
            "timestamp": {"$gte": cutoff_date},
            # Длина > 30 символов, чтобы отсеять "Ок", "Буду", "Во сколько?"
            "$expr": {"$gt": [{"$strLenCP": "$content"}, 30]}, 
            # Поиск по регулярке (регистронезависимый)
            "content": {"$regex": regex_pattern, "$options": "i"}
        }

        logging.info(f"🔎 Scanning chat {chat_id} for announcements (Last {days} days)...")
        
        # ВАЖНО: Мы не фильтруем по message_thread_id, ищем ВЕЗДЕ.
        # Лимит ставим побольше (10), чтобы захватить разные варианты анонсов.
        cursor = self.messages.find(query).sort("timestamp", -1).limit(limit)
        events = await cursor.to_list(length=limit)
        return events

    async def add_sticker(self, file_id, emoji):
        exists = await self.stickers.find_one({"file_id": file_id})
        if not exists:
            await self.stickers.insert_one({"file_id": file_id, "emoji": emoji})

    async def get_random_sticker(self):
        pipeline = [{"$sample": {"size": 1}}]
        result = await self.stickers.aggregate(pipeline).to_list(length=1)
        return result[0]['file_id'] if result else None
