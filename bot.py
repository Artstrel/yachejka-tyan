import asyncio
import logging
import sys
import socket
import random
import os

# --- FIX IPv4 для Fly.io ---
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
# ВАЖНО: Добавили импорт is_event_query
from services.ai_engine import generate_response, is_event_query 
from keep_alive import start_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)

dp = Dispatcher()
db = Database(config.DATABASE_URL)
bot = Bot(
    token=config.TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
BOT_INFO = None

# ... (Startup/Shutdown без изменений) ...

async def on_startup(dispatcher: Dispatcher):
    logging.info("🚀 Запуск процессов...")
    if config.DATABASE_URL:
        try:
            await db.connect()
            logging.info("✅ MongoDB подключена")
        except Exception as e:
            logging.error(f"❌ Ошибка подключения к БД: {e}")

    global BOT_INFO
    BOT_INFO = await bot.get_me()
    logging.info(f"🤖 Авторизован как @{BOT_INFO.username}")
    start_server()

async def on_shutdown(dispatcher: Dispatcher):
    logging.warning("🛑 Bot stopping...")

dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)

@dp.message(F.text | F.photo | F.sticker)
async def main_handler(message: types.Message):
    if not BOT_INFO: return

    chat_id = message.chat.id
    thread_id = message.message_thread_id
    user_name = message.from_user.first_name if message.from_user else "Anon"
    text = message.text or message.caption or ""
    
    # Логируем (полезно для отладки)
    # logging.info(f"📩 Msg: {text[:20]}...") 

    # 1. Сохраняем стикеры
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text: text = f"[Sticker {message.sticker.emoji}]"

    # === ФИЛЬТРЫ ОТВЕТА (ГЛАВНОЕ ИЗМЕНЕНИЕ) ===
    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply_to_me = message.reply_to_message and \
                     message.reply_to_message.from_user.id == BOT_INFO.id
    
    # Проверяем, вопрос ли это про ивент
    is_event_question = is_event_query(text)

    # Шанс ответа для ОБЫЧНОГО флуда
    chance = 0.15 
    
    # ЛОГИКА:
    # Отвечаем, если:
    # 1. Меня тегнули (is_mentioned)
    # 2. Это реплай мне (is_reply_to_me)
    # 3. Это ВОПРОС ПРО ИВЕНТ (is_event_question) <--- НОВОЕ УСЛОВИЕ
    # 4. Или просто повезло (random > chance)
    
    should_answer = is_mentioned or is_reply_to_me or is_event_question or (random.random() < chance)

    if not should_answer:
        # Если не отвечаем, то просто сохраняем в базу (чтобы помнить контекст) и выходим
        if config.DATABASE_URL:
            # Используем create_task, чтобы не тормозить
            asyncio.create_task(db.add_message(chat_id, message.from_user.id, user_name, 'user', text, thread_id))
        return

    # Если мы здесь — значит, бот решил ответить!
    try: await bot.send_chat_action(chat_id=chat_id, action="typing")
    except: pass

    # Фото
    image_data = None
    if message.photo:
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            downloaded = await bot.download_file(file.file_path)
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(downloaded.read()))
            if not text: text = "[Photo]"
        except Exception: pass

    # Сохраняем сообщение юзера перед ответом
    if config.DATABASE_URL:
        await db.add_message(chat_id, message.from_user.id, user_name, 'user', text, thread_id)

    # Генерация ответа
    # Передаем bot, чтобы AI мог проверить закрепы
# Генерация
    ai_reply = await generate_response(db, chat_id, text, bot, image_data)

    # ИСПРАВЛЕНИЕ: Проверяем, что ответ не пустой
    if not ai_reply: 
        return

    try:
        sent_msg = await message.reply(ai_reply)
        
        if config.DATABASE_URL:
            asyncio.create_task(db.add_message(chat_id, BOT_INFO.id, "Bot", 'model', ai_reply, thread_id))

        # Стикер (если уместно)
        if config.DATABASE_URL and random.random() < 0.3:
            sticker_id = await db.get_random_sticker()
            if sticker_id:
                try:
                    await asyncio.sleep(1)
                    await bot.send_sticker(chat_id=chat_id, sticker=sticker_id, message_thread_id=thread_id)
                except Exception: pass

    except Exception as e:
        logging.error(f"❌ Ошибка отправки: {e}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("📡 Запуск Polling...")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот выключен вручную")
