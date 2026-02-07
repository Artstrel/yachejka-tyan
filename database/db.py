import logging
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import sys
import os
import asyncio
import random  # <--- Добавляем для выборки стикера

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class Database:
    def __init__(self, dsn):
        self.dsn = dsn
        self.client = None
        self.db = None

    async def connect(self):
        try:
            self.client = AsyncIOMotorClient(self.dsn)
            await self.client.admin.command('ping')
            self.db = self.client[config.DB_NAME]
            
            # Индексы для сообщений
            await self.db.messages.create_index("chat_id")
            await self.db.messages.create_index([("chat_id", 1), ("created_at", -1)])
            
            # Индекс для стикеров (чтобы не дублировать)
            await self.db.stickers.create_index("file_id", unique=True)
            
            logging.info("✅ Успешное подключение к MongoDB")
        except Exception as e:
            logging.error(f"❌ Ошибка подключения к MongoDB: {e}")
            raise e

    async def add_message(self, chat_id, user_id, user_name, role, content):
        """Сохранение сообщения"""
        document = {
            "chat_id": chat_id,
            "user_id": user_id,
            "user_name": user_name,
            "role": role,
            "content": content,
            "created_at": datetime.utcnow()
        }
        await self.db.messages.insert_one(document)

    async def get_context(self, chat_id, limit=8):
        """Получение истории чата"""
        cursor = self.db.messages.find({"chat_id": chat_id}).sort("created_at", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        return reversed(history)

    async def get_median_length(self, chat_id, limit=15):
        """Медианная длина сообщений (для подстройки краткости)"""
        cursor = self.db.messages.find({"chat_id": chat_id, "role": "user"}).sort("created_at", -1).limit(limit)
        messages = await cursor.to_list(length=limit)
        lengths = [len(m['content']) for m in messages if len(m.get('content', '')) > 5]
        if not lengths: return 0
        sorted_len = sorted(lengths)
        return sorted_len[len(sorted_len) // 2]

    # --- НОВЫЕ МЕТОДЫ ДЛЯ СТИКЕРОВ ---

    async def add_sticker(self, file_id, emoji=None):
        """Сохраняет стикер в коллекцию (ворует у пользователей)"""
        try:
            await self.db.stickers.update_one(
                {"file_id": file_id},
                {
                    "$setOnInsert": {
                        "file_id": file_id, 
                        "emoji": emoji, 
                        "created_at": datetime.utcnow()
                    }
                },
                upsert=True
            )
        except Exception as e:
            logging.error(f"Ошибка сохранения стикера: {e}")

    async def get_random_sticker(self):
        """Достает случайный стикер из накопленной базы"""
        try:
            pipeline = [{"$sample": {"size": 1}}]
            cursor = self.db.stickers.aggregate(pipeline)
            result = await cursor.to_list(length=1)
            return result[0]['file_id'] if result else None
        except Exception as e:
            logging.error(f"Ошибка получения стикера: {e}")
            return None
