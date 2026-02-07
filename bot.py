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
from services.ai_engine import generate_response
from keep_alive import start_server

# Логирование в stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)

# Инициализация объектов
dp = Dispatcher()
db = Database(config.DATABASE_URL)
bot = Bot(
    token=config.TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
BOT_INFO = None

# --- СОБЫТИЯ ЖИЗНЕННОГО ЦИКЛА (Startup/Shutdown) ---

async def on_startup(dispatcher: Dispatcher):
    """Срабатывает при запуске бота"""
    logging.info("🚀 Запуск процессов...")
    
    # 1. Подключение к БД
    if config.DATABASE_URL:
        try:
            await db.connect()
            logging.info("✅ MongoDB подключена")
        except Exception as e:
            logging.error(f"❌ Ошибка подключения к БД: {e}")

    # 2. Получение инфо о боте
    global BOT_INFO
    BOT_INFO = await bot.get_me()
    logging.info(f"🤖 Авторизован как @{BOT_INFO.username}")

    # 3. Запуск Health Check сервера (в отдельном потоке)
    start_server()

async def on_shutdown(dispatcher: Dispatcher):
    """Срабатывает при остановке (деплой, перезагрузка)"""
    logging.warning("🛑 Получен сигнал остановки. Завершаю работу...")
    
    # Закрываем БД (если у клиента есть метод close, иначе просто логируем)
    logging.info("💤 Соединения закрыты. Bye-bye.")

# Регистрируем хуки
dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)

# --- ХЕНДЛЕРЫ ---

@dp.message(F.text | F.photo | F.sticker)
async def main_handler(message: types.Message):
    # Если бот еще не прогрузился
    if not BOT_INFO: return

    chat_id = message.chat.id
    user_name = message.from_user.first_name if message.from_user else "Anon"
    text = message.text or message.caption or ""
    
    # Лог для отладки
    logging.info(f"📩 Message from {user_name}: {text[:30]}...")

    # Стикеры
    if message.sticker and config.DATABASE_URL:
        await db.add_sticker(message.sticker.file_id, message.sticker.emoji)
        if not text: text = f"[Sticker {message.sticker.emoji}]"

    # Фильтры (Reply, Mention, Random)
    is_mentioned = text and f"@{BOT_INFO.username}" in text
    is_reply_to_me = message.reply_to_message and \
                     message.reply_to_message.from_user.id == BOT_INFO.id
    
    if not (is_mentioned or is_reply_to_me) and random.random() > 0.04:
        return

    # Typing...
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

    # Сохранение (asyncio.create_task для скорости)
    if config.DATABASE_URL:
        asyncio.create_task(db.add_message(chat_id, message.from_user.id, user_name, 'user', text))
ai_reply = await generate_response(db, chat_id, text, image_data)

    # ПРОВЕРКА: Если ответа нет (закончились токены или ошибка), просто выходим
    if ai_reply is None:
        return

    # Отправка ответа (произойдет только если токены НЕ закончились)
    try:
        await message.reply(ai_reply)
        if config.DATABASE_URL:
            asyncio.create_task(db.add_message(chat_id, BOT_INFO.id, "Bot", 'model', ai_reply))
    except Exception as e:
        logging.error(f"❌ Ошибка отправки: {e}")

# --- ТОЧКА ВХОДА ---

async def main():
    # Удаляем вебхук и все накопившиеся апдейты, чтобы не отвечать на старье
    await bot.delete_webhook(drop_pending_updates=True)
    
    logging.info("📡 Запуск Polling...")
    # allowed_updates оптимизирует трафик, получая только нужное
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот выключен вручную")
