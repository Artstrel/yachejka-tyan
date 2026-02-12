import asyncio
import logging
import sys
import socket
import random
import re
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
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
# ИСПРАВЛЕНИЕ: ReactionTypeEmoji берем из types, а не из enums
from aiogram.types import BotCommand, ReactionTypeEmoji

import config
from database.db import Database
from services.ai_engine import generate_response, is_event_query, is_summary_query, analyze_and_save_memory, get_available_models_text
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

# === ФУНКЦИЯ ВЕЧНОГО СТАТУСА ПЕЧАТИ ===
async def keep_typing(chat_id, bot, thread_id=None, sleep_time=4):
    """
    Постоянно обновляет статус 'typing', пока задача не будет отменена.
    """
    try:
        while True:
            await bot.send_chat_action(
                chat_id=chat_id, 
                action=ChatAction.TYPING, 
                message_thread_id=thread_id
            )
            await asyncio.sleep(sleep_time)
    except asyncio.CancelledError:
        pass 
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
    
    commands = [
        BotCommand(command="start", description="👋 Приветствие"),
        BotCommand(command="summary", description="📜 Краткая сводка"),
        BotCommand(command="events", description="📅 Анонсы"),
        BotCommand(command="models", description="🤖 Модели"),
        BotCommand(command="help", description="❓ Помощь")
    ]
    await bot.set_my_commands(commands)
    start_server()

async def on_shutdown(dispatcher: Dispatcher):
    logging.warning("🛑 Bot stopping...")

dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)

# Хендлер для команды /models
@dp.message(F.command("models"))
async def models_handler(message: types.Message):
    text = get_available_models_text()
    await message.reply(text, parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text | F.photo | F.sticker)
async def main_handler(message: types.Message):
    if not BOT_INFO: return

    chat_id = message.chat.id
    thread_id = message.message_thread_id 
    msg_id = message.message_id
    user_id = message.from_user.id
    user_name = message.from_user.first_name if message.from_user else "Anon"
    text = message.text or message.caption or ""
    
    # 1. Сохраняем стикеры
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text: text = f"[Sticker {message.sticker.emoji}]"

    # === ФИЛЬТРЫ ===
    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply_to_me = message.reply_to_message and \
                     message.reply_to_message.from_user.id == BOT_INFO.id
    
    is_event = is_event_query(text)
    is_summary = is_summary_query(text)
    is_command = text.startswith("/")

    chance = 0.15 
    should_answer = is_command or is_mentioned or is_reply_to_me or is_event or is_summary or (random.random() < chance)

    # Сохраняем сообщение и запускаем анализ памяти
    if config.DATABASE_URL:
        await db.add_message(chat_id, msg_id, user_id, user_name, 'user', text, thread_id)
        asyncio.create_task(analyze_and_save_memory(db, chat_id, user_id, user_name, text))

    if not should_answer:
        return

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
            if not text: text = "Что на этом фото?"
        except Exception: pass

    # === ЗАПУСК ИНДИКАТОРА "ПЕЧАТАЕТ..." ===
    typing_task = asyncio.create_task(keep_typing(chat_id, bot, thread_id))

    try:
        # Генерация ответа
        ai_reply = await generate_response(db, chat_id, text, bot, image_data, user_id=user_id)
    finally:
        typing_task.cancel()

    if not ai_reply:
        return

    # === ОБРАБОТКА ТЕГОВ ИЗ ОТВЕТА ===
    
    # 1. Реакции [REACT:🔥]
    explicit_reaction = None
    reaction_match = re.search(r"\[REACT:(.+?)\]", ai_reply)
    if reaction_match:
        explicit_reaction = reaction_match.group(1).strip()
        ai_reply = ai_reply.replace(reaction_match.group(0), "")

    # 2. Стикеры [STICKER]
    send_sticker_flag = False
    if re.search(r"(\[?STICKER\]?)", ai_reply, re.IGNORECASE):
        send_sticker_flag = True
        ai_reply = re.sub(r"(\[?STICKER\]?)", "", ai_reply, flags=re.IGNORECASE)

    # 3. Чистка мусора
    ai_reply = re.sub(r"\*.*?\*", "", ai_reply)
    ai_reply = re.sub(r"^\(.*\)\s*", "", ai_reply) 
    ai_reply = re.sub(r"(?i)^[\*\s]*(Yachejkatyanbot|Yachejka-tyan|Bot|Assistant|System|Name)[\*\s]*:?\s*", "", ai_reply).strip()

    try:
        # Отправляем текст
        if ai_reply:
            sent_msg = await message.reply(ai_reply)
            
            if config.DATABASE_URL:
                asyncio.create_task(db.add_message(chat_id, sent_msg.message_id, BOT_INFO.id, "Bot", 'model', ai_reply, thread_id))

        # === ЛОГИКА РЕАКЦИЙ ===
        reaction_to_set = explicit_reaction
        if not reaction_to_set and random.random() < 0.05:
             reaction_to_set = random.choice(['👍', '❤', '🔥', '👏', '😁', '🤔', '👀'])

        if reaction_to_set:
            try:
                await bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=msg_id, 
                    reaction=[ReactionTypeEmoji(emoji=reaction_to_set)]
                )
            except Exception: pass

        # === ЛОГИКА СТИКЕРОВ ===
        if (send_sticker_flag or random.random() < 0.08) and config.DATABASE_URL:
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
