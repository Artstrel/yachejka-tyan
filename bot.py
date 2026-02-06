import asyncio
import logging
import sys
import socket
import random

# -----------------------------------------------------------
# 🚑 ЛЕЧЕНИЕ СЕТИ HUGGING FACE (FIX IPv6/DNS Error)
# -----------------------------------------------------------
try:
    # Сохраняем оригинальную функцию
    orig_getaddrinfo = socket.getaddrinfo

    # Создаем обертку, которая подменяет IPv6 на IPv4
    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        # Передаем аргументы позиционно (важно для socket!)
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    # Подменяем функцию в библиотеке socket
    socket.getaddrinfo = getaddrinfo_ipv4
except Exception as e:
    pass
# -----------------------------------------------------------

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Импорты наших модулей
import config
from database.db import Database
from services.ai_engine import generate_response
from keep_alive import start_server

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация глобальных переменных
dp = Dispatcher()
bot = None
db = Database(config.DATABASE_URL)

# --- Хэндлеры ---
@dp.message(F.text | F.photo)
async def main_handler(message: types.Message):
    global bot
    
    # 1. Сначала определяем ВСЕ базовые переменные
    chat_id = message.chat.id
    # Получаем текст из сообщения или подписи к фото
    text = message.text or message.caption or ""
    user_name = message.from_user.first_name
    
    # 2. Проверка: это обращение к боту?
    bot_info = await bot.get_me()
    is_mentioned = text and f"@{bot_info.username}" in text
    is_reply_to_me = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    # 3. Логика ответа (Фильтр)
    # Если это НЕ прямое обращение...
    if not (is_mentioned or is_reply_to_me):
        # ...и рандом не выпал (шанс 3% - так безопаснее для чата на 800 чел)
        if random.random() > 0.03: 
            return
            
    # 4. Пропускаем совсем пустые сообщения (без фото и текста)
    if not text and not message.photo:
        return

    # 5. Индикация и обработка фото
    image_data = None
    status_msg = None
    
    # Индикатор печати (чтобы пользователь видел реакцию)
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    if message.photo:
        try:
            # Тут можно было бы послать "Смотрю...", но лучше не спамить лишним сообщением
            pass 
            
            # Скачивание фото
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            file_path = file.file_path
            downloaded = await bot.download_file(file_path)
            
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(downloaded.read()))
            
            # Если текста нет, помечаем для логов
            if not text:
                text = "[Отправил фото]"
        except Exception as e:
            logging.error(f"Ошибка обработки фото: {e}")
            text = text or "[Ошибка загрузки фото]"

    # 6. Сохраняем сообщение ЮЗЕРА в БД
    if config.DATABASE_URL:
        try:
            await db.add_message(chat_id, message.from_user.id, user_name, 'user', text)
        except Exception as e:
            logging.error(f"Ошибка БД (сохранение юзера): {e}")

    # 7. Генерация ответа
    ai_reply = await generate_response(db, chat_id, text, image_data)

    # 8. Отправка ответа
    try:
        await message.reply(ai_reply)
    except Exception as e:
        # Если Markdown сломался, пробуем без него
        try:
            await message.reply(ai_reply, parse_mode=None)
        except Exception as e2:
            logging.error(f"Не удалось отправить ответ: {e2}")

    # 9. Сохраняем ответ БОТА в БД
    if config.DATABASE_URL:
        try:
            await db.add_message(chat_id, bot_info.id, "Ячейка-тян", 'model', ai_reply)
        except Exception as e:
            logging.error(f"Ошибка БД (лог бота): {e}")

# --- Запуск ---

async def main():
    global bot
    print("🚀 Запуск Ячейки-тян 2.0...")
    
    # Инициализация бота (обычная, без сложных коннекторов)
    bot = Bot(
        token=config.TELEGRAM_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    
    # Подключение к БД
    if config.DATABASE_URL:
        try:
            await db.connect()
            print("✅ База данных подключена")
        except Exception as e:
            print(f"❌ Ошибка БД: {e}")
            print("⚠️ Бот работает без памяти")
    
    # Запуск веб-сервера (для HF Spaces)
    await start_server()
    
    # Запуск поллинга
    print("📡 Поллинг запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")