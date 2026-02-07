import asyncio
import logging
import sys
import socket
import random

# --- FIX IPv6/DNS ---
try:
    orig_getaddrinfo = socket.getaddrinfo
    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = getaddrinfo_ipv4
except Exception:
    pass
# --------------------

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
from database.db import Database
from services.ai_engine import generate_response
from keep_alive import start_server

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()
bot = None
db = Database(config.DATABASE_URL)
BOT_INFO = None  # Глобальная переменная для кэширования инфо о боте

@dp.message(F.text | F.photo | F.sticker)
async def main_handler(message: types.Message):
    global bot, BOT_INFO
    
    # Логируем каждое входящее сообщение для диагностики
    user_name = message.from_user.first_name if message.from_user else "Anon"
    logging.info(f"Получено сообщение от {user_name} (ID: {message.from_user.id})")

    if BOT_INFO is None:
        BOT_INFO = await bot.get_me()

    chat_id = message.chat.id
    text = message.text or message.caption or ""
    
    # --- ПРОВЕРКА ФИЛЬТРОВ ---
    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply_to_me = message.reply_to_message and \
                     message.reply_to_message.from_user.id == BOT_INFO.id
    
    # ВНИМАНИЕ: Для тестов можно временно снизить порог random.random()
    if not (is_mentioned or is_reply_to_me) and random.random() > 0.04:
        # Логируем пропуск сообщения по шансу
        logging.info(f"Сообщение в чате {chat_id} пропущено (шанс 4%)")
        return
        
    # --- ВОРОВСТВО СТИКЕРОВ ---
    if message.sticker and config.DATABASE_URL:
        # Сохраняем стикер (асинхронно, не блокируя основной поток, если бы не await)
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text:
            emoji_part = f" {message.sticker.emoji}" if message.sticker.emoji else ""
            text = f"[Стикер{emoji_part}]"

    # --- ФИЛЬТРЫ ---
    # Проверка на упоминание
    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply_to_me = message.reply_to_message and \
                     message.reply_to_message.from_user.id == BOT_INFO.id
    
    # Шанс 4% (для чата на 800 чел это норм)
    if not (is_mentioned or is_reply_to_me) and random.random() > 0.04:
        return
        
    # Пропуск пустых технических сообщений
    if not text and not message.photo and not message.sticker:
        return

    # --- ОБРАБОТКА ---
    image_data = None
    
    # Индикатор "печатает"
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    if message.photo:
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            # Скачиваем в память
            downloaded = await bot.download_file(file.file_path)
            
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(downloaded.read()))
            if text == "": text = "[Фото]"
        except Exception as e:
            logging.error(f"Ошибка фото: {e}")

    # Сохраняем сообщение юзера
    if config.DATABASE_URL:
        # run_task позволяет не ждать завершения записи в БД, чтобы ответить быстрее
        asyncio.create_task(db.add_message(chat_id, message.from_user.id, user_name, 'user', text))

    # Генерация ответа
    ai_reply = await generate_response(db, chat_id, text, image_data)

    # Отправка ответа
    try:
        await message.reply(ai_reply)
    except Exception:
        try:
            await message.reply(ai_reply, parse_mode=None)
        except Exception:
            pass

    # Сохраняем ответ бота
    if config.DATABASE_URL:
        asyncio.create_task(db.add_message(chat_id, BOT_INFO.id, "Bot", 'model', ai_reply))
            
    # --- ОТПРАВКА СТИКЕРА (БОНУС) ---
    if config.DATABASE_URL and random.random() < 0.15:
        sticker_id = await db.get_random_sticker()
        if sticker_id:
            try:
                await asyncio.sleep(1) 
                await bot.send_sticker(chat_id, sticker_id)
            except Exception as e:
                logging.error(f"Не удалось отправить стикер: {e}")

async def main():
    global bot, BOT_INFO
    print("🚀 Запуск Ячейки-тян...")
    
    bot = Bot(token=config.TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    
    # Кэшируем инфо о боте ОДИН раз при запуске
    BOT_INFO = await bot.get_me()
    print(f"🤖 Бот авторизован: @{BOT_INFO.username}")
    
    if config.DATABASE_URL:
        try:
            await db.connect() #
            print("✅ БД подключена.")
        except Exception as e:
            print(f"❌ Ошибка БД: {e}")
    
    start_server() #
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
