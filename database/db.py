import motor.motor_asyncio
from datetime import datetime, timedelta
import logging
import re

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

    async def add_message(self, chat_id, user_id, user_name, role, content):
        await self.messages.insert_one({
            "chat_id": chat_id,
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

    async def get_median_length(self, chat_id, limit=20):
        cursor = self.messages.find({"chat_id": chat_id, "role": "user"}).sort("timestamp", -1).limit(limit)
        messages = await cursor.to_list(length=limit)
        if not messages: return 0
        lengths = [len(m['content']) for m in messages]
        return sum(lengths) / len(lengths)

    # --- ИСПРАВЛЕННЫЙ ПОИСК АНОНСОВ ---
    async def get_potential_announcements(self, chat_id, days=5, limit=5):
        """
        Ищет сообщения с ссылками или ключевыми словами событий.
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Ключевые слова (регистронезависимые)
        keywords = ["вход", "цена", "начало", "сбор", "регистрация", "📍", "📅", "анонс", "состоится"]
        regex_kw = "|".join([re.escape(k) for k in keywords])

        cursor = self.messages.find({
            "chat_id": chat_id,
            "role": "user",
            "timestamp": {"$gte": cutoff_date},
            # Условие: (Есть ссылка) ИЛИ (Есть ключевое слово И длина > 30 символов)
            "$or": [
                {"content": {"$regex": "http", "$options": "i"}}, 
                {"$and": [
                    {"content": {"$regex": regex_kw, "$options": "i"}},
                    {"$expr": {"$gt": [{"$strLenCP": "$content"}, 30]}}
                ]}
            ]
        }).sort("timestamp", -1).limit(limit)

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
