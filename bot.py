import asyncio
import logging
import sys
import socket
import random  # Обязательно нужен для рандома!

# --- FIX IPv6/DNS (для Hugging Face и некоторых серверов) ---
try:
    orig_getaddrinfo = socket.getaddrinfo
    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = getaddrinfo_ipv4
except Exception:
    pass
# -----------------------------------------------------------

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

# Добавляем F.sticker в фильтр, чтобы бот видел стикеры
@dp.message(F.text | F.photo | F.sticker)
async def main_handler(message: types.Message):
    global bot
    
    # 1. Инициализация переменных (чтобы не было ошибок UnboundLocalError)
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    text = message.text or message.caption or ""
    
    # 2. "ВОРОВСТВО" СТИКЕРОВ
    # Если пользователь прислал стикер, сохраняем его в базу
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        # Для истории сообщений помечаем, что был стикер
        if not text:
            emoji_part = f" {message.sticker.emoji}" if message.sticker.emoji else ""
            text = f"[Стикер{emoji_part}]"

    # 3. Фильтр ответов (кому и когда отвечать)
    bot_info = await bot.get_me()
    is_mentioned = text and f"@{bot_info.username}" in text
    is_reply_to_me = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    # Шанс ответа (снизил до 4% для общего чата, чтобы не душнил)
    # Если это не личное обращение, бот молчит в 96% случаев
    if not (is_mentioned or is_reply_to_me) and random.random() > 0.04:
        return
        
    # Пустые сообщения (технические) пропускаем
    if not text and not message.photo and not message.sticker:
        return

    # 4. Обработка контента
    image_data = None
    
    # Индикатор "печатает..."
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    if message.photo:
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            file_path = file.file_path
            downloaded = await bot.download_file(file_path)
            
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(downloaded.read()))
            if text == "": text = "[Фото]"
        except Exception as e:
            logging.error(f"Ошибка фото: {e}")

    # 5. Сохраняем входящее сообщение в историю
    if config.DATABASE_URL:
        try:
            await db.add_message(chat_id, message.from_user.id, user_name, 'user', text)
        except Exception as e:
            logging.error(f"Ошибка сохранения в БД: {e}")

    # 6. Генерируем ответ через AI
    ai_reply = await generate_response(db, chat_id, text, image_data)

    # 7. Отправляем ответ
    try:
        await message.reply(ai_reply)
    except Exception:
        try:
            await message.reply(ai_reply, parse_mode=None)
        except Exception:
            pass

    # 8. Сохраняем ответ бота
    if config.DATABASE_URL:
        try:
            await db.add_message(chat_id, bot_info.id, "Bot", 'model', ai_reply)
        except Exception:
            pass
            
    # 9. БОНУС: Отправка случайного стикера из коллекции
    # С шансом 15% бот может кинуть стикер после своего ответа
    if config.DATABASE_URL and random.random() < 0.15:
        sticker_id = await db.get_random_sticker()
        if sticker_id:
            try:
                await asyncio.sleep(1) # Небольшая пауза для естественности
                await bot.send_sticker(chat_id, sticker_id)
            except Exception as e:
                logging.error(f"Не удалось отправить стикер: {e}")

# --- Запуск ---
async def main():
    global bot
    print("🚀 Запуск Ячейки-тян (Sticker Edition)...")
    
    bot = Bot(token=config.TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    
    if config.DATABASE_URL:
        try:
            await db.connect()
            print("✅ БД подключена. Режим накопления стикеров активен.")
        except Exception as e:
            print(f"❌ Ошибка БД: {e}")
    
    await start_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")