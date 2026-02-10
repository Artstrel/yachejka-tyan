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
        # Берем последние сообщения именно из ТЕКУЩЕЙ ветки обсуждения? 
        # Или вообще из всего чата? 
        # Обычно для контекста диалога лучше брать просто последние сообщения по chat_id.
        # Если хотите контекст только текущей ветки, нужно добавить фильтр по message_thread_id,
        # но пока оставим как есть (общий контекст).
        cursor = self.messages.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        return history[::-1]

    # --- ПОИСК АНОНСОВ ПО ВСЕМУ ЧАТУ ---
    async def get_potential_announcements(self, chat_id, days=21, limit=5):
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Ключевые слова (Regex)
        keywords = [
            # Локации
            "d22", "red&wine", "red & wine", "coffee lars", "amaghleba", "tabukashvili",
            # Время и дни
            r"\d{1,2}:\d{2}",  # 19:00
            "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
            "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря",
            # Маркеры
            "ячейка", "сбор", "собираемся", "вход", "начало", "powerpoint", "киберслав", "аниме", "просмотр"
        ]
        
        regex_pattern = "|".join(keywords)

        # Мы просто ищем по chat_id. Это захватит ВСЕ ветки/топики группы.
        query = {
            "chat_id": chat_id,
            "role": "user",
            "timestamp": {"$gte": cutoff_date},
            "$expr": {"$gt": [{"$strLenCP": "$content"}, 40]}, # Игнорируем короткие сообщения
            "content": {"$regex": regex_pattern, "$options": "i"}
        }

        # Больше никаких if config.THREAD_ID! Просто ищем везде.
        logging.info(f"🔎 Scanning ALL topics in chat {chat_id} for announcements...")
        
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
