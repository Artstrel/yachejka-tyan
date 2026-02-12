import motor.motor_asyncio
import datetime
import random
import logging

class Database:
    def __init__(self, uri):
        self.uri = uri
        self.client = None
        self.db = None

    async def connect(self):
        if not self.uri:
            logging.warning("⚠️ No DATABASE_URL provided. DB features disabled.")
            return
        try:
            self.client = motor.motor_asyncio.AsyncIOMotorClient(self.uri)
            self.db = self.client.get_database()
            # Проверка соединения
            await self.client.admin.command('ping')
            logging.info("✅ Connected to MongoDB")
        except Exception as e:
            logging.error(f"❌ Failed to connect to MongoDB: {e}")

    # --- CHAT HISTORY ---
    async def add_message(self, chat_id, message_id, user_id, user_name, role, content, thread_id=None):
        if not self.db: return
        msg = {
            "chat_id": chat_id,
            "message_id": message_id,
            "user_id": user_id,
            "user_name": user_name,
            "role": role,
            "content": content,
            "thread_id": thread_id,
            "timestamp": datetime.datetime.utcnow()
        }
        await self.db.messages.insert_one(msg)

    async def get_context(self, chat_id, limit=15): # Лимит увеличен до 15
        if not self.db: return []
        cursor = self.db.messages.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
        messages = await cursor.to_list(length=limit)
        return messages[::-1]

    # --- STICKERS ---
    async def add_sticker(self, file_id, emoji):
        if not self.db: return
        existing = await self.db.stickers.find_one({"file_id": file_id})
        if not existing:
            await self.db.stickers.insert_one({"file_id": file_id, "emoji": emoji})

    async def get_random_sticker(self):
        if not self.db: return None
        pipeline = [{"$sample": {"size": 1}}]
        result = await self.db.stickers.aggregate(pipeline).to_list(length=1)
        return result[0]['file_id'] if result else None

    # --- EVENTS (ANNOUNCEMENTS) ---
    async def get_potential_announcements(self, chat_id, days=60, limit=5):
        if not self.db: return []
        # Простая логика: ищем сообщения с датами или ключевыми словами за последние дни
        # В идеале тут нужен векторный поиск, но пока берем просто свежие сообщения
        # которые длиннее 50 символов (потенциальные анонсы)
        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        cursor = self.db.messages.find({
            "chat_id": chat_id,
            "timestamp": {"$gte": since},
            "role": "user",
            "$or": [
                {"content": {"$regex": "анонс", "$options": "i"}},
                {"content": {"$regex": "встреч", "$options": "i"}},
                {"content": {"$regex": "собираемся", "$options": "i"}},
                {"content": {"$regex": "сбор", "$options": "i"}}
            ]
        }).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    # === НОВОЕ: ДОЛГОСРОЧНАЯ ПАМЯТЬ (FACTS) ===
    async def add_fact(self, chat_id, user_id, user_name, fact_text):
        """Сохраняет важный факт о пользователе или событии"""
        if not self.db: return
        fact = {
            "chat_id": chat_id,
            "user_id": user_id,
            "user_name": user_name,
            "fact": fact_text,
            "timestamp": datetime.datetime.utcnow()
        }
        await self.db.memory.insert_one(fact)
        logging.info(f"💾 Memory saved: {user_name} -> {fact_text}")

    async def get_relevant_facts(self, chat_id, user_id, limit=5):
        """Достает факты о конкретном юзере + общие факты чата"""
        if not self.db: return []
        
        # 1. Факты об этом юзере
        cursor_user = self.db.memory.find({"chat_id": chat_id, "user_id": user_id}).sort("timestamp", -1).limit(3)
        user_facts = await cursor_user.to_list(length=3)
        
        # 2. Последние общие факты (чтобы помнить контекст беседы других)
        cursor_global = self.db.memory.find({"chat_id": chat_id, "user_id": {"$ne": user_id}}).sort("timestamp", -1).limit(2)
        global_facts = await cursor_global.to_list(length=2)
        
        return user_facts + global_facts
