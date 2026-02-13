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

# Базовый список безопасных реакций (Telegram иногда меняет его, но основные работают)
SAFE_REACTIONS = {
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂", "🤷‍♀", "🤷"
}

async def keep_typing(chat_id, bot, thread_id=None, sleep_time=4):
    """Показывает индикатор печати"""
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
    """Инициализация при старте бота"""
    start_server()
    logging.info("✅ Web server started (health check passed)")

    logging.info("🚀 Запуск бота...")
    if config.DATABASE_URL:
        try:
            await db.connect()
        except Exception as e:
            logging.error(f"⚠️ DB Connect warning: {e}")
            
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
    """Обработчик команды /models"""
    text = get_available_models_text()
    await message.reply(text, parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text | F.photo | F.sticker)
async def main_handler(message: types.Message):
    """Основной обработчик сообщений"""
    if not BOT_INFO:
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id
    msg_id = message.message_id
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    text = message.text or message.caption or ""
    
    # Обработка стикеров
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text:
            text = f"[Sticker {message.sticker.emoji}]"

    # Определяем, нужно ли отвечать
    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO.id
    is_cmd = text.startswith("/")
    chance = 0.15

    should_answer = is_cmd or is_mentioned or is_reply or (random.random() < chance)
    
    # Сохраняем сообщение в БД
    if config.DATABASE_URL:
        await db.add_message(chat_id, msg_id, user_id, user_name, 'user', text, thread_id)
        
        # Асинхронно анализируем и сохраняем факты
        # ОПТИМИЗАЦИЯ: Чтобы не получать Error 429, запускаем анализ редко:
        # 1. Если бот решил ответить (should_answer)
        # 2. ИЛИ с шансом 5% для обычных сообщений
        # 3. И только если текст длиннее 20 символов
        if (should_answer or random.random() < 0.05) and len(text) > 20:
            asyncio.create_task(analyze_and_save_memory(db, chat_id, user_id, user_name, text))

    if not should_answer:
        return

    # Обработка изображений
    image_data = None
    if message.photo:
        try:
            f = await bot.get_file(message.photo[-1].file_id)
            down = await bot.download_file(f.file_path)
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(down.read()))
            if not text:
                text = "Что на этом фото?"
        except Exception as e:
            logging.error(f"Image download error: {e}")

    # Запускаем индикатор печати
    typing_task = asyncio.create_task(keep_typing(chat_id, bot, thread_id))
    
    try:
        # Генерируем ответ
        ai_reply = await generate_response(
            db, chat_id, thread_id, text, bot, 
            image_data, user_id=user_id
        )
        
        if not ai_reply:
            return

        # === ОБРАБОТКА ТЕГОВ ===
        
        # 1. Извлекаем реакцию
        explicit_reaction = None
        reaction_match = re.search(r"\[?REACT:[\s]*([^\s\]]+)\]?", ai_reply, re.IGNORECASE)
        if reaction_match:
            raw_reaction = reaction_match.group(1).strip()
            # Проверяем, есть ли эмодзи в безопасном списке
            if raw_reaction in SAFE_REACTIONS:
                explicit_reaction = raw_reaction
            
            ai_reply = ai_reply.replace(reaction_match.group(0), "")

        # 2. Извлекаем флаг стикера
        send_sticker_flag = False
        if re.search(r"(\[?STICKER\]?)", ai_reply, re.IGNORECASE):
            send_sticker_flag = True
            ai_reply = re.sub(r"(\[?STICKER\]?)", "", ai_reply, flags=re.IGNORECASE)

        # 3. Очищаем ответ от артефактов
        ai_reply = re.sub(r"\*.*?\*", "", ai_reply)  # Убираем *action*
        ai_reply = re.sub(r"^\(.*\)\s*", "", ai_reply)  # Убираем (мысли)
        ai_reply = re.sub(
            r"(?i)^[\*\s]*(Yachejkatyanbot|Yachejka-tyan|Bot|Assistant|System|Name|Ячейка)[\*\s]*:?\s*",
            "", ai_reply
        ).strip()

        # === ОТПРАВКА ОТВЕТА ===
        
        sent_message = None
        
        # Отправляем текст если есть
        if ai_reply:
            try:
                sent_message = await message.reply(ai_reply)
                if config.DATABASE_URL:
                    await db.add_message(
                        chat_id, sent_message.message_id, 
                        BOT_INFO.id, "Bot", 'model', ai_reply, thread_id
                    )
            except Exception as e:
                logging.error(f"Failed to send message: {e}")
        
        # Обрабатываем стикер или реакцию
        if send_sticker_flag:
            sticker_to_send = await db.get_random_sticker() if config.DATABASE_URL else None
            if sticker_to_send:
                await asyncio.sleep(0.5)
                try:
                    await bot.send_sticker(
                        chat_id=chat_id,
                        sticker=sticker_to_send,
                        message_thread_id=thread_id
                    )
                    logging.info("📎 Sticker sent")
                except Exception: pass
        elif explicit_reaction:
            try:
                await bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=msg_id,
                    reaction=[ReactionTypeEmoji(emoji=explicit_reaction)]
                )
                logging.info(f"✨ Reaction set: {explicit_reaction}")
            except TelegramBadRequest as e:
                if "REACTION_INVALID" in str(e):
                    logging.warning(f"⚠️ Invalid reaction ignored: {explicit_reaction}")
                else:
                    logging.warning(f"Reaction error: {e}")
            except Exception as e:
                logging.warning(f"Reaction error: {e}")

    except Exception as e:
        logging.error(f"Interaction error: {e}")
    finally:
        # Выключаем индикатор печати
        typing_task.cancel()

async def main():
    """Точка входа"""
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
