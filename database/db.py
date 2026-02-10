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

    async def add_message(self, chat_id, message_id, user_id, user_name, role, content, thread_id=None):
        if content is None: content = ""
        await self.messages.insert_one({
            "chat_id": chat_id,
            "message_id": message_id,
            "message_thread_id": thread_id,
            "user_id": user_id,
            "user_name": user_name,
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow()
        })

    async def get_context(self, chat_id, limit=10):
        cursor = self.messages.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        return history[::-1]

    async def get_chat_history_for_summary(self, chat_id, limit=300):
        query = {"chat_id": chat_id, "role": "user"}
        cursor = self.messages.find(query).sort("timestamp", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        return history[::-1]

    async def get_potential_announcements(self, chat_id, days=60, limit=10):
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # --- БЕЗОПАСНЫЙ ЗАПРОС ---
        # Мы убираем $strLenCP из прямого вызова и используем $type: "string" как жесткий фильтр
        
        # 1. ПОИСК В ВЕТКЕ АНОНСОВ
        if config.ANNOUNCEMENT_THREAD_ID:
            tid = int(config.ANNOUNCEMENT_THREAD_ID)
            query = {
                "timestamp": {"$gte": cutoff_date},
                "content": {"$type": "string", "$ne": ""}, # Только непустые строки
            }
            if tid < 0: 
                query["chat_id"] = tid 
            else:
                query["chat_id"] = chat_id
                query["message_thread_id"] = tid
            
            # Мы убрали проверку длины на уровне базы, чтобы не падало.
            # Отфильтруем короткие сообщения уже в Python (это безопасно и быстро).
            
            cursor = self.messages.find(query).sort("timestamp", -1).limit(limit * 2) # Берем с запасом
            raw_data = await cursor.to_list(length=limit * 2)
            
            # Python-фильтрация длины
            filtered = [msg for msg in raw_data if len(msg.get('content', '')) > 15]
            return filtered[:limit]

        # 2. ГЛОБАЛЬНЫЙ ПОИСК
        logging.info("🔎 Keyword scan mode (Broad search)")
        keywords = [
            "аниме", "anime", "тайтл", "title", "серия", "эпизод", "сезон", 
            "онгоинг", "премьера", "показ", "screen", "watch", "смотрим", "просмотр",
            "кино", "фильм", "мульт", 
            "презентаци", "powerpoint", "лекция", "спикер", "воркшоп", "мастер-класс",
            "english", "speaking", "английский", "клуб", "club",
            "квиз", "quiz", "мафия", "mafia", "настол", "играем", "игра", "башн", "clocktower",
            "караоке", "karaoke", "party", "тусовка", "вечер", "dr", "др", "день рождения",
            "d22", "red&wine", "red & wine", "coffee lars", "amaghleba", "tabukashvili",
            r"\d{1,2}:\d{2}"
        ]
        regex_pattern = "|".join(keywords)

        query = {
            "chat_id": chat_id,
            "role": "user",
            "timestamp": {"$gte": cutoff_date},
            "content": {"$type": "string", "$regex": regex_pattern, "$options": "i"}
        }
        
        # Тоже фильтруем длину в Python
        cursor = self.messages.find(query).sort("timestamp", -1).limit(30)
        raw_data = await cursor.to_list(length=30)
        filtered = [msg for msg in raw_data if len(msg.get('content', '')) > 30]
        
        return filtered[:limit]

    async def add_sticker(self, file_id, emoji):
        exists = await self.stickers.find_one({"file_id": file_id})
        if not exists:
            await self.stickers.insert_one({"file_id": file_id, "emoji": emoji})

    async def get_random_sticker(self):
        pipeline = [{"$sample": {"size": 1}}]
        result = await self.stickers.aggregate(pipeline).to_list(length=1)
        return result[0]['file_id'] if result else None
