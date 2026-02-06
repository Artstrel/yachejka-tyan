import logging
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import sys
import os
import asyncio

# Добавляем родительскую директорию в путь поиска, если запускаем файл напрямую
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

class Database:
    def __init__(self, dsn):
        self.dsn = dsn
        self.client = None
        self.db = None

    async def connect(self):
        """Подключение к MongoDB"""
        try:
            self.client = AsyncIOMotorClient(self.dsn)
            # Motor ленивый, он не подключится пока мы не сделаем запрос.
            # Сделаем тестовую команду ping, чтобы убедиться в связи.
            await self.client.admin.command('ping')
            
            self.db = self.client[config.DB_NAME]
            
            # Создаем индексы (фон)
            await self.db.messages.create_index("chat_id")
            await self.db.messages.create_index([("chat_id", 1), ("created_at", -1)])
            
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
            "role": role,          # 'user' или 'model'
            "content": content,
            "created_at": datetime.utcnow()
        }
        await self.db.messages.insert_one(document)

    async def get_context(self, chat_id, limit=20):
        """Получение истории чата"""
        cursor = self.db.messages.find(
            {"chat_id": chat_id}
        ).sort("created_at", -1).limit(limit)
        
        history = await cursor.to_list(length=limit)
        return reversed(history)

    async def get_median_length(self, chat_id, limit=15):
        """Вычисление медианной длины сообщений пользователя"""
        cursor = self.db.messages.find(
            {
                "chat_id": chat_id, 
                "role": "user",
            }
        ).sort("created_at", -1).limit(limit)
        
        messages = await cursor.to_list(length=limit)
        
        lengths = [len(m['content']) for m in messages if len(m.get('content', '')) > 5]
        
        if not lengths:
            return 0
            
        sorted_len = sorted(lengths)
        return sorted_len[len(sorted_len) // 2]


if __name__ == "__main__":
    # Настройка логирования для теста
    logging.basicConfig(level=logging.INFO)
    
    async def test_connection():
        print("🔌 Проверка подключения к БД...")
        if not config.DATABASE_URL:
            print("❌ DATABASE_URL не задан в .env")
            return
            
        try:
            db = Database(config.DATABASE_URL)
            await db.connect()
            print(f"✅ Успешно подключено к базе: {config.DB_NAME}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

    asyncio.run(test_connection())