import asyncio
import logging
import sys
import socket
import random
import os

# --- FIX IPv4 (Важно для стабильности на Fly.io) ---
try:
    orig_getaddrinfo = socket.getaddrinfo
    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = getaddrinfo_ipv4
except Exception:
    pass

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
from database.db import Database
from services.ai_engine import generate_response
from keep_alive import start_server

# Настройка логирования в stdout для fly logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)

dp = Dispatcher()
db = Database(config.DATABASE_URL)
bot = None
BOT_INFO = None

@dp.message(F.text | F.photo | F.sticker)
async def main_handler(message: types.Message):
    global BOT_INFO
    
    if BOT_INFO is None:
        BOT_INFO = await bot.get_me()

    chat_id = message.chat.id
    user_name = message.from_user.first_name if message.from_user else "Anon"
    text = message.text or message.caption or ""
    
    # Лог входящего сообщения
    logging.info(f"📩 Сообщение от {user_name} в {chat_id}: {text[:50]}...")

    # ВОРОВСТВО СТИКЕРОВ
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text:
            text = f"[Стикер {message.sticker.emoji or ''}]"

    # ФИЛЬТРЫ (Mention или 4% шанс)
    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply_to_me = message.reply_to_message and \
                     message.reply_to_message.from_user.id == BOT_INFO.id
    
    if not (is_mentioned or is_reply_to_me) and random.random() > 0.04:
        return

    # Индикация печати
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except:
        pass

    # Обработка фото
    image_data = None
    if message.photo:
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            downloaded = await bot.download_file(file.file_path)
            
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(downloaded.read()))
            if not text: text = "[Фото]"
        except Exception as e:
            logging.error(f"❌ Ошибка загрузки фото: {e}")

    # Сохранение в БД
    if config.DATABASE_URL:
        asyncio.create_task(db.add_message(chat_id, message.from_user.id, user_name, 'user', text))

    # Генерация ответа
    ai_reply = await generate_response(db, chat_id, text, image_data)

    # Отправка
    try:
        await message.reply(ai_reply)
        if config.DATABASE_URL:
            asyncio.create_task(db.add_message(chat_id, BOT_INFO.id, "Bot", 'model', ai_reply))
    except Exception as e:
        logging.error(f"❌ Ошибка отправки: {e}")

async def main():
    global bot, BOT_INFO
    logging.info("🚀 Запуск Ячейки-тян на Fly.io...")
    
    bot = Bot(
        token=config.TELEGRAM_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    
    try:
        BOT_INFO = await bot.get_me()
        logging.info(f"🤖 Бот авторизован: @{BOT_INFO.username}")
    except Exception as e:
        logging.error(f"❌ Критическая ошибка авторизации: {e}")
        return

    if config.DATABASE_URL:
        try:
            await db.connect()
            logging.info("✅ База данных подключена")
        except Exception as e:
            logging.error(f"❌ Ошибка БД: {e}")
    
    # Запуск Flask сервера (Health Check для Fly.io)
    start_server()
    
    # Очистка очереди обновлений и старт
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("📡 Начинаю polling...")
    
    # Запуск polling. Это бесконечный цикл.
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")
