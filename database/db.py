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
            
            # === ФИКС ОШИБКИ "No default database defined" ===
            try:
                # Пытаемся взять имя базы из ссылки
                self.db = self.client.get_database()
            except Exception:
                # Если в ссылке нет имени, используем дефолтное
                logging.warning("⚠️ No DB name in URI, using default 'yachejka_bot'")
                self.db = self.client.get_database("yachejka_bot")

            # Проверка соединения
            await self.client.admin.command('ping')
            logging.info("✅ Connected to MongoDB")
            
        except Exception as e:
            logging.error(f"❌ Failed to connect to MongoDB: {e}")
            self.db = None # Чтобы бот не падал при попытке записи, а просто пропускал

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

    async def get_context(self, chat_id, limit=15):
        if self.db is None: return []
        try:
            cursor = self.db.messages.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
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
            cursor = self.db.
