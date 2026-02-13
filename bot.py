import asyncio
import logging
import sys
import socket
import random
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, ReactionTypeEmoji
from aiogram.exceptions import TelegramBadRequest
import config
from database.db import Database
from services.ai_engine import generate_response, get_available_models_text, analyze_and_save_memory
from keep_alive import start_server

# Fix IPv4
try:
    orig_getaddrinfo = socket.getaddrinfo
    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = getaddrinfo_ipv4
except Exception:
    pass

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

dp = Dispatcher()
db = Database(config.DATABASE_URL)
bot = Bot(token=config.TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
BOT_INFO = None

SAFE_REACTIONS = {
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂", "🤷‍♀", "🤷"
}

async def keep_typing(chat_id, bot, thread_id=None, sleep_time=4):
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING, message_thread_id=thread_id)
            await asyncio.sleep(sleep_time)
    except: pass

async def on_startup(dispatcher: Dispatcher):
    start_server()
    if config.DATABASE_URL:
        await db.connect()
            
    global BOT_INFO
    BOT_INFO = await bot.get_me()
    await bot.set_my_commands([
        BotCommand(command="start", description="👋 Привет"),
        BotCommand(command="summary", description="📜 Сводка"),
        BotCommand(command="events", description="📅 Анонсы"),
        BotCommand(command="models", description="🤖 Модели"),
    ])
    logging.info(f"✅ Bot started as @{BOT_INFO.username}")

dp.startup.register(on_startup)

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
    user_name = message.from_user.first_name
    text = message.text or message.caption or ""
    
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text: text = f"[Sticker {message.sticker.emoji}]"

    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO.id
    is_cmd = text.startswith("/")
    
    should_answer = is_cmd or is_mentioned or is_reply or (random.random() < 0.15)
    
    if config.DATABASE_URL:
        await db.add_message(chat_id, msg_id, user_id, user_name, 'user', text, thread_id)
        if (should_answer or random.random() < 0.02) and len(text) > 25:
            asyncio.create_task(analyze_and_save_memory(db, chat_id, user_id, user_name, text))

    if not should_answer: return

    image_data = None
    # Исправлена ошибка отступа здесь:
    if message.photo:
        try:
            f = await bot.get_file(message.photo[-1].file_id)
            down = await bot.download_file(f.file_path)
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(down.read()))
            if not text: text = "Что на фото?"
        except: pass

    typing_task = asyncio.create_task(keep_typing(chat_id, bot, thread_id))
    
    try:
        ai_reply = await generate_response(db, chat_id, thread_id, text, bot, image_data, user_id=user_id)
        if not ai_reply: return

        # === ПАРСИНГ ОТВЕТА (УЛУЧШЕННЫЙ) ===
        
        # 1. Сначала извлекаем REACT
        explicit_reaction = None
        reaction_match = re.search(r"\[?REACT:[\s]*([^\s\]]+)\]?", ai_reply, re.IGNORECASE)
        if reaction_match:
            raw = reaction_match.group(1).strip()
            if raw in SAFE_REACTIONS: explicit_reaction = raw
            ai_reply = ai_reply.replace(reaction_match.group(0), "")

        # 2. Ищем STICKER
        send_sticker = False
        sticker_match = re.search(r"\[STICKER.*?\]", ai_reply, re.IGNORECASE)
        if sticker_match:
            send_sticker = True
            ai_reply = ai_reply.replace(sticker_match.group(0), "")

        # 3. Чистка мусора
        ai_reply = re.sub(r"\*.*?\*", "", ai_reply) 
        ai_reply = re.sub(r"^\(.*\)\s*", "", ai_reply)
        ai_reply = re.sub(r"(?i)^[\*\s]*(Yachejka|Ячейка|Bot)[\*\s]*:?\s*", "", ai_reply).strip()
        ai_reply = re.sub(r"[:\s]*.*\]$", "", ai_reply).strip() 

        # === АВТО-СТИКЕРЫ ===
        if not send_sticker and config.DATABASE_URL:
            chance = 0.1 if len(ai_reply) < 20 else 0.02
            if random.random() < chance:
                send_sticker = True

        # === ОТПРАВКА ===
        if ai_reply:
            try:
                sent = await message.reply(ai_reply)
                if config.DATABASE_URL:
                    await db.add_message(chat_id, sent.message_id, BOT_INFO.id, "Bot", 'model', ai_reply, thread_id)
            except: pass
        
        if send_sticker:
            sticker_id = await db.get_random_sticker() if config.DATABASE_URL else None
            if sticker_id:
                await asyncio.sleep(0.5)
                try:
                    await bot.send_sticker(chat_id=chat_id, sticker=sticker_id, message_thread_id=thread_id)
                except: pass
        elif explicit_reaction:
            try:
                await bot.set_message_reaction(chat_id=chat_id, message_id=msg_id, reaction=[ReactionTypeEmoji(emoji=explicit_reaction)])
            except: pass

    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        typing_task.cancel()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
