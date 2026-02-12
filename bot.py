import asyncio
import logging
import sys
import socket
import random
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
import config
from database.db import Database
# Импортируем новую функцию анализа памяти
from services.ai_engine import generate_response, get_available_models_text, analyze_and_save_memory
from keep_alive import start_server

# Fix IPv4
try:
    orig_getaddrinfo = socket.getaddrinfo
    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = getaddrinfo_ipv4
except Exception: pass

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

dp = Dispatcher()
db = Database(config.DATABASE_URL)
bot = Bot(token=config.TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
BOT_INFO = None

async def keep_typing(chat_id, bot, sleep_time=4):
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(sleep_time)
    except: pass

async def on_startup(dispatcher: Dispatcher):
    logging.info("🚀 Запуск...")
    if config.DATABASE_URL: await db.connect()
    global BOT_INFO
    BOT_INFO = await bot.get_me()
    await bot.set_my_commands([
        BotCommand(command="start", description="👋 Привет"),
        BotCommand(command="summary", description="📜 Сводка"),
        BotCommand(command="events", description="📅 Анонсы"),
        BotCommand(command="models", description="🤖 Модели"),
    ])
    start_server()

dp.startup.register(on_startup)

@dp.message(F.command("models"))
async def models_handler(message: types.Message):
    text = get_available_models_text()
    await message.reply(text, parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text | F.photo | F.sticker)
async def main_handler(message: types.Message):
    if not BOT_INFO: return

    chat_id = message.chat.id
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    text = message.text or message.caption or ""
    
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text: text = f"[Sticker {message.sticker.emoji}]"

    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO.id
    is_cmd = text.startswith("/")
    chance = 0.15 

    should_answer = is_cmd or is_mentioned or is_reply or (random.random() < chance)
    
    # 1. СОХРАНЯЕМ СООБЩЕНИЕ
    if config.DATABASE_URL:
        await db.add_message(chat_id, message.message_id, user_id, 
                             user_name, 'user', text, message.message_thread_id)
        
        # 2. ЗАПУСКАЕМ АНАЛИЗ ПАМЯТИ (В ФОНЕ)
        # Бот не ждет этого, он сразу идет отвечать
        asyncio.create_task(analyze_and_save_memory(db, chat_id, user_id, user_name, text))

    if not should_answer: return

    image_data = None
    if message.photo:
        try:
            f = await bot.get_file(message.photo[-1].file_id)
            down = await bot.download_file(f.file_path)
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(down.read()))
            if not text: text = "Что на этом фото?"
        except: pass

    typing_task = asyncio.create_task(keep_typing(chat_id, bot))
    
    try:
        # Передаем user_id чтобы достать факты
        ai_reply = await generate_response(db, chat_id, text, bot, image_data, user_id=user_id)
    finally:
        typing_task.cancel()

    if not ai_reply: return

    # Очистка
    send_sticker_flag = False
    if re.search(r"(\[?STICKER\]?)", ai_reply, re.IGNORECASE):
        send_sticker_flag = True
        ai_reply = re.sub(r"(\[?STICKER\]?)", "", ai_reply, flags=re.IGNORECASE)

    ai_reply = re.sub(r"\*.*?\*", "", ai_reply)
    ai_reply = re.sub(r"^\(.*\)\s*", "", ai_reply) 
    ai_reply = re.sub(r"(?i)^[\*\s]*(Yachejkatyanbot|Yachejka-tyan|Bot|Assistant|System|Name)[\*\s]*:?\s*", "", ai_reply).strip()

    try:
        if ai_reply:
            sent = await message.reply(ai_reply)
            if config.DATABASE_URL:
                await db.add_message(chat_id, sent.message_id, BOT_INFO.id, "Bot", 'model', ai_reply, message.message_thread_id)
        
        if (send_sticker_flag or random.random() < 0.02) and config.DATABASE_URL:
            sid = await db.get_random_sticker()
            if sid:
                await asyncio.sleep(1)
                await bot.send_sticker(chat_id=chat_id, sticker=sid, message_thread_id=message.message_thread_id)
    except Exception as e:
        logging.error(f"Send error: {e}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
