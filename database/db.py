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
            try:
                self.db = self.client.get_database()
            except Exception:
                logging.warning("⚠️ No DB name in URI, using default 'yachejka_bot'")
                self.db = self.client.get_database("yachejka_bot")

            await self.client.admin.command('ping')
            logging.info("✅ Connected to MongoDB")
            
        except Exception as e:
            logging.error(f"❌ Failed to connect to MongoDB: {e}")
            self.db = None

    # --- CHAT HISTORY ---
    async def add_message(self, chat_id, message_id, user_id, user_name, role, content, thread_id=None):
        if self.db is None: return
        try:
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
        except Exception as e:
            logging.error(f"DB Write Error: {e}")

    # ОБНОВЛЕНО: Добавлен thread_id для фильтрации по топикам
    async def get_context(self, chat_id, thread_id=None, limit=15):
        if self.db is None: return []
        try:
            query = {"chat_id": chat_id}
            # Если это топик (thread_id не None и не 0), фильтруем строго по нему
            if thread_id:
                query["thread_id"] = thread_id
            
            cursor = self.db.messages.find(query).sort("timestamp", -1).limit(limit)
            messages = await cursor.to_list(length=limit)
            return messages[::-1]
        except Exception:
            return []

    # --- STICKERS ---
    async def add_sticker(self, file_id, emoji):
        if self.db is None: return
        try:
            existing = await self.db.stickers.find_one({"file_id": file_id})
            if not existing:
                await self.db.stickers.insert_one({"file_id": file_id, "emoji": emoji})
        except Exception: pass

    async def get_random_sticker(self):
        if self.db is None: return None
        try:
            pipeline = [{"$sample": {"size": 1}}]
            result = await self.db.stickers.aggregate(pipeline).to_list(length=1)
            return result[0]['file_id'] if result else None
        except Exception: return None

    # --- EVENTS ---
    async def get_potential_announcements(self, chat_id, days=60, limit=5):
        if self.db is None: return []
        try:
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
        except Exception: return []

    # --- MEMORY (FACTS) ---
    async def add_fact(self, chat_id, user_id, user_name, fact_text):
        if self.db is None: return
        try:
            fact = {
                "chat_id": chat_id,
                "user_id": user_id,
                "user_name": user_name,
                "fact": fact_text,
                "timestamp": datetime.datetime.utcnow()
            }
            await self.db.memory.insert_one(fact)
            logging.info(f"💾 Memory saved: {user_name} -> {fact_text}")
        except Exception as e:
            logging.error(f"Memory Save Error: {e}")

    async def get_relevant_facts(self, chat_id, user_id, limit=5):
        if self.db is None: return []
        try:
            cursor_user = self.db.memory.find({"chat_id": chat_id, "user_id": user_id}).sort("timestamp", -1).limit(3)
            user_facts = await cursor_user.to_list(length=3)
            
            cursor_global = self.db.memory.find({"chat_id": chat_id, "user_id": {"$ne": user_id}}).sort("timestamp", -1).limit(2)
            global_facts = await cursor_global.to_list
