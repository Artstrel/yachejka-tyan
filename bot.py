import asyncio
import logging
import sys
import os

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web  # Импортируем веб-сервер aiohttp

import config
from database.db import Database
from services.ai_engine import generate_response

# Настройка логгера
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Инициализация
dp = Dispatcher()
db = Database(config.DATABASE_URL)
bot = Bot(
    token=config.TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)

# --- ВЕБ-СЕРВЕР (HEALTH CHECK) ---
async def health_check(request):
    return web.Response(text="I am alive!", status=200)

async def start_web_server():
    """Запускает легкий веб-сервер на aiohttp"""
    app = web.Application()
    app.router.add_get('/', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render передает порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 10000))
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"✅ Веб-сервер запущен на порту {port}")

# --- ХЭНДЛЕРЫ ---
@dp.message(F.text | F.photo)
async def main_handler(message: types.Message):
    user = message.from_user.first_name
    text = message.text or message.caption or ""
    
    logger.info(f"📩 Сообщение от {user}")

    if config.DATABASE_URL:
        asyncio.create_task(db.add_message(message.chat.id, message.from_user.id, user, 'user', text))

    image_data = None
    if message.photo:
        status_msg = await message.reply("👀")
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            downloaded = await bot.download_file(file.file_path)
            
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(downloaded.read()))
        except Exception as e:
            logger.error(f"Ошибка фото: {e}")
        finally:
            await status_msg.delete()

    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        ai_reply = await generate_response(db, message.chat.id, text, image_data)
        await message.reply(ai_reply)

        if config.DATABASE_URL:
             bot_user = await bot.get_me()
             asyncio.create_task(db.add_message(message.chat.id, bot_user.id, "Bot", 'model', ai_reply))

    except Exception as e:
        logger.error(f"Ошибка AI: {e}")
        await message.reply("Что-то пошло не так...")

# --- ЗАПУСК ---
async def main():
    logger.info("🚀 Запуск на Render (Native Async Mode)...")
    
    # 1. Запускаем веб-сервер (теперь через await, так как это aiohttp!)
    await start_web_server()

    # 2. Подключаем БД
    if config.DATABASE_URL:
        await db.connect()
        logger.info("✅ База данных подключена")

    # 3. Чистим вебхуки и стартуем
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("📡 Поллинг запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
