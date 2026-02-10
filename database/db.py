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
        # Обычный контекст для разговора
        cursor = self.messages.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        return history[::-1]

    # --- НОВАЯ ЛОГИКА ПОИСКА ---
    async def get_potential_announcements(self, chat_id, days=30, limit=5):
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # ВАРИАНТ 1: Если мы знаем ID ветки анонсов -> Читаем только её
        if config.ANNOUNCEMENT_THREAD_ID:
            logging.info(f"🎯 Targeted fetch from Thread ID: {config.ANNOUNCEMENT_THREAD_ID}")
            
            # Если это отдельный КАНАЛ (ID начинается с -100...), то ищем по chat_id = этому ID
            # Если это ВЕТКА в группе, то ищем по chat_id группы + message_thread_id ветки
            
            query = {
                "timestamp": {"$gte": cutoff_date},
                "$expr": {"$gt": [{"$strLenCP": "$content"}, 20]} # Игнорируем совсем короткие
            }

            # Проверка: ID похож на канал или на ветку?
            tid = int(config.ANNOUNCEMENT_THREAD_ID)
            if tid < 0: 
                # Это канал (например -10012345)
                query["chat_id"] = tid
            else:
                # Это ветка в текущей группе
                query["chat_id"] = chat_id
                query["message_thread_id"] = tid

            # Берем последние 5 сообщений из этой ветки. 
            # Считаем, что в ветке анонсов всё важное.
            cursor = self.messages.find(query).sort("timestamp", -1).limit(limit)
            return await cursor.to_list(length=limit)

        # ВАРИАНТ 2: Если ID нет -> Ищем по всему чату (Медленный режим)
        logging.info("🔎 Global scan mode (No Thread ID set)")
        keywords = [
            "аниме", "anime", "тайтл", "title", "серия", "эпизод", "сезон", 
            "онгоинг", "премьера", "показ", "screen", "watch", "смотрим", "просмотр",
            "кино", "фильм", "мульт", "презентаци", "powerpoint", "квиз", "quiz",
            "мафия", "mafia", "настол", "играем", "игра", "башн", "clocktower",
            "d22", "red&wine", "red & wine", "coffee lars",
            r"\d{1,2}:\d{2}"
        ]
        regex_pattern = "|".join(keywords)

        query = {
            "chat_id": chat_id,
            "role": "user",
            "timestamp": {"$gte": cutoff_date},
            "$expr": {"$gt": [{"$strLenCP": "$content"}, 30]}, 
            "content": {"$regex": regex_pattern, "$options": "i"}
        }
        
        cursor = self.messages.find(query).sort("timestamp", -1).limit(20) # Лимит 20 для скорости
        return await cursor.to_list(length=20)

    async def add_sticker(self, file_id, emoji):
        exists = await self.stickers.find_one({"file_id": file_id})
        if not exists:
            await self.stickers.insert_one({"file_id": file_id, "emoji": emoji})

    async def get_random_sticker(self):
        pipeline = [{"$sample": {"size": 1}}]
        result = await self.stickers.aggregate(pipeline).to_list(length=1)
        return result[0]['file_id'] if result else None
