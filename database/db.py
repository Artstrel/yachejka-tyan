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
        cursor = self.messages.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        return history[::-1]

    # --- ОБНОВЛЕННЫЙ ПОИСК АНОНСОВ ---
    async def get_potential_announcements(self, chat_id, days=21, limit=5):
        # Увеличил days до 21, так как анонсы могут висеть долго
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Базовый список ключевых слов на основе твоих примеров
        keywords = [
            # Локации (включая вариации из примеров)
            "d22", "red&wine", "red & wine", "coffee lars", "amaghleba", "tabukashvili",
            # Время и даты
            r"\d{1,2}:\d{2}",  # 19:00, 20:00
            "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
            "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря",
            # Маркеры анонсов
            "ячейка", "сбор", "собираемся", "вход", "начало", "powerpoint", "киберслав", "аниме", "просмотр"
        ]
        
        # Формируем регулярку: (слово1|слово2|слово3)
        # re.escape не используем для времени, но для текста полезно, если есть спецсимволы
        regex_pattern = "|".join(keywords)

        query = {
            "chat_id": chat_id,
            "role": "user",
            "timestamp": {"$gte": cutoff_date},
            # Фильтр по длине: анонсы обычно длинные. 
            # Отсекаем короткие сообщения "ок", "приду", чтобы не засорять контекст.
            "$expr": {"$gt": [{"$strLenCP": "$content"}, 40]},
            
            # Ищем совпадение хотя бы одного ключевого слова (регистронезависимо)
            "content": {"$regex": regex_pattern, "$options": "i"}
        }

        # Если задан ID топика анонсов, приоритет ему, но ищем везде, 
        # так как часто кидают анонсы и в общий чат
        if config.ANNOUNCEMENT_THREAD_ID and config.ANNOUNCEMENT_THREAD_ID != 0:
             # Логика: ИЛИ сообщение из топика анонсов, ИЛИ содержит ключевые слова
             query = {
                "$or": [
                    {"message_thread_id": config.ANNOUNCEMENT_THREAD_ID},
                    query
                ]
             }

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
