import motor.motor_asyncio
from datetime import datetime, timedelta
import logging

class Database:
    def __init__(self, uri, db_name="yachejka_bot"):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self.client[db_name]
        self.messages = self.db.messages
        self.stickers = self.db.stickers

    async def connect(self):
        # Проверка соединения
        try:
            await self.client.admin.command('ping')
            logging.info("Pinged your deployment. You successfully connected to MongoDB!")
        except Exception as e:
            logging.error(f"MongoDB connection error: {e}")

    async def add_message(self, chat_id, user_id, user_name, role, content):
        """Сохраняет сообщение в историю"""
        await self.messages.insert_one({
            "chat_id": chat_id,
            "user_id": user_id,
            "user_name": user_name,
            "role": role, # 'user' или 'model'
            "content": content,
            "timestamp": datetime.utcnow()
        })

    async def get_context(self, chat_id, limit=10):
        """Получает последние N сообщений для контекста диалога"""
        cursor = self.messages.find(
            {"chat_id": chat_id}
        ).sort("timestamp", -1).limit(limit)
        
        history = await cursor.to_list(length=limit)
        return history[::-1] # Разворачиваем, чтобы было от старых к новым

    async def get_median_length(self, chat_id, limit=20):
        """Считает среднюю длину сообщений (для адаптивности)"""
        cursor = self.messages.find(
            {"chat_id": chat_id, "role": "user"}
        ).sort("timestamp", -1).limit(limit)
        
        messages = await cursor.to_list(length=limit)
        if not messages:
            return 0
        
        lengths = [len(m['content']) for m in messages]
        return sum(lengths) / len(lengths)

    # --- НОВЫЙ МЕТОД: ПОИСК АНОНСОВ ---
    async def get_potential_announcements(self, chat_id, days=7, limit=5):
        """
        Ищет сообщения за последние дни, похожие на анонсы.
        Критерии: длинные сообщения, содержат ссылки или ключевые слова.
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Ключевые слова, указывающие на ивент
        keywords = [
            "http", "t.me/", "запись", "вход", "цена", "начало в", 
            "состоится", "пройдет", "анонс", "геолокация", "📍", "📅"
        ]
        
        # Строим RegEx запрос: ищем любое из ключевых слов
        regex_pattern = "|".join([re.escape(k) for k in keywords if "http" not in k])
        # Для http отдельная проверка, так как re.escape экранирует слеши
        
        cursor = self.messages.find({
            "chat_id": chat_id,
            "role": "user", # Ищем только то, что писали люди (не бот)
            "timestamp": {"$gte": cutoff_date},
            "$or": [
                {"content": {"$regex": "http", "$options": "i"}}, # Содержит ссылку
                {"content": {"$regex": regex_pattern, "$options": "i"}} # Или ключевые слова
            ],
            # Отсекаем слишком короткие сообщения (приветы и т.д.)
            "$expr": {"$gt": [{"$strLenCP": "$content"}, 50]} 
        }).sort("timestamp", -1).limit(limit)

        events = await cursor.to_list(length=limit)
        return events

    # --- Sticker Methods ---
    async def add_sticker(self, file_id, emoji):
        # Проверяем, нет ли уже такого стикера
        exists = await self.stickers.find_one({"file_id": file_id})
        if not exists:
            await self.stickers.insert_one({
                "file_id": file_id,
                "emoji": emoji,
                "timestamp": datetime.utcnow()
            })

    async def get_random_sticker(self):
        pipeline = [{"$sample": {"size": 1}}]
        result = await self.stickers.aggregate(pipeline).to_list(length=1)
        if result:
            return result[0]['file_id']
        return None

import re # Не забываем импортировать re для regex
