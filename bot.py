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
from aiogram.types import BotCommand # <--- Добавили тип для команд

import config
from database.db import Database
# ВАЖНО: Добавили is_summary_query
from services.ai_engine import generate_response, is_event_query, is_summary_query
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

# Добавляем новую функцию для вечного статуса
async def keep_typing_action(chat_id, bot, sleep_time=4):
    """Постоянно отправляет статус 'typing', пока задачу не отменят."""
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(sleep_time)
    except asyncio.CancelledError:
        pass # Задача отменена, просто выходим
    except Exception:
        pass

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
    
    # --- АВТОМАТИЧЕСКАЯ УСТАНОВКА КОМАНД ---
    # Чтобы не бегать в BotFather каждый раз
    commands = [
        BotCommand(command="start", description="👋 Приветствие"),
        BotCommand(command="summary", description="📜 Краткая сводка (о чем говорили)"),
        BotCommand(command="events", description="📅 Анонсы и встречи"),
        BotCommand(command="help", description="❓ Помощь")
    ]
    await bot.set_my_commands(commands)
    logging.info("✅ Команды бота обновлены")

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
    msg_id = message.message_id
    user_name = message.from_user.first_name if message.from_user else "Anon"
    text = message.text or message.caption or ""
    
    
    # 1. Сохраняем стикеры
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text: text = f"[Sticker {message.sticker.emoji}]"

    # === ФИЛЬТРЫ ОТВЕТА ===
    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply_to_me = message.reply_to_message and \
                     message.reply_to_message.from_user.id == BOT_INFO.id
    
    # Проверки на тип вопроса
    is_event = is_event_query(text)
    is_summary = is_summary_query(text)
    is_command = text.startswith("/") # <--- Любая команда (напр. /start)

    chance = 0.15 
    
    # ЛОГИКА: Отвечаем, если это команда, вопрос про ивент, саммари, тег или рандом
    should_answer = is_command or is_mentioned or is_reply_to_me or is_event or is_summary or (random.random() < chance)

    # Сохраняем сообщение юзера (даже если не отвечаем)
    if config.DATABASE_URL:
        # Используем await, чтобы гарантировать порядок сообщений
        await db.add_message(chat_id, msg_id, message.from_user.id, user_name, 'user', text, thread_id)

    if not should_answer:
        return

 # Запускаем "печатает..." в фоновом режиме
    typing_task = asyncio.create_task(keep_typing_action(chat_id, bot))

    # Фото
    image_data = None
    if message.photo:
        try:
            # ... (код обработки фото тот же) ...
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            downloaded = await bot.download_file(file.file_path)
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(downloaded.read()))
            if not text: text = "[Photo]"
        except Exception: pass

    try:
        # Генерация ответа (пока она идет, typing_task работает)
        ai_reply = await generate_response(db, chat_id, text, bot, image_data)
    finally:
        # Как только получили ответ (или ошибку) — отменяем статус
        typing_task.cancel()

    if not ai_reply:
        return

    try:
        sent_msg = await message.reply(ai_reply)
        
        # Стикер
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
