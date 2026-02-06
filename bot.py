import asyncio
import logging
import sys
import socket

# -----------------------------------------------------------
# 🚑 ЛЕЧЕНИЕ СЕТИ HUGGING FACE (FIX IPv6/DNS Error)
# -----------------------------------------------------------
try:
    # Сохраняем оригинальную функцию
    orig_getaddrinfo = socket.getaddrinfo

    # Создаем обертку, которая подменяет IPv6 на IPv4
    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        # Передаем аргументы позиционно (важно для socket!)
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    # Подменяем функцию в библиотеке socket
    socket.getaddrinfo = getaddrinfo_ipv4
except Exception as e:
    pass
# -----------------------------------------------------------

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Импорты наших модулей
import config
from database.db import Database
from services.ai_engine import generate_response
from keep_alive import start_server

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация глобальных переменных
dp = Dispatcher()
bot = None
db = Database(config.DATABASE_URL)

# --- Хэндлеры ---

@dp.message(F.text | F.photo)
async def main_handler(message: types.Message):
    global bot
    
    user_name = message.from_user.first_name
    chat_id = message.chat.id
    text = message.text or message.caption or ""
    
    # 1. Пропускаем пустые сообщения
    if not text and not message.photo:
        return

    # 2. Обработка картинки
    image_data = None
    status_msg = None
    
    if message.photo:
        try:
            status_msg = await bot.send_message(chat_id, "👀 Смотрю...", reply_to_message_id=message.message_id)
        except Exception:
            pass # Не страшно, если не отправилось
            
        # Скачивание фото
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            file_path = file.file_path
            downloaded = await bot.download_file(file_path)
            
            import io
            from PIL import Image
            image_data = Image.open(io.BytesIO(downloaded.read()))
            text = text or "[Отправил фото]"
        except Exception as e:
            logging.error(f"Ошибка фото: {e}")
            text = text or "[Ошибка загрузки фото]"

    else:
        # Индикатор печати
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

    # 3. Сохраняем сообщение в БД
    if config.DATABASE_URL:
        try:
            await db.add_message(chat_id, message.from_user.id, user_name, 'user', text)
        except Exception as e:
            logging.error(f"Ошибка БД (сохранение): {e}")

    # 4. Генерация ответа
    ai_reply = await generate_response(db, chat_id, text, image_data)

    # 5. Отправка ответа
    try:
        await message.reply(ai_reply)
    except Exception as e:
        # Если Markdown сломался, отправляем как простой текст
        try:
            await message.reply(ai_reply, parse_mode=None)
        except Exception as e2:
            logging.error(f"Не удалось отправить ответ: {e2}")

    # 6. Сохраняем ответ бота в БД
    if config.DATABASE_URL:
        try:
            bot_user = await bot.get_me()
            await db.add_message(chat_id, bot_user.id, "Ячейка-тян", 'model', ai_reply)
        except Exception as e:
            logging.error(f"Ошибка БД (лог бота): {e}")
        
    # Удаляем сообщение "Смотрю..."
    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass

# --- Запуск ---

async def main():
    global bot
    print("🚀 Запуск Ячейки-тян 2.0...")
    
    # Инициализация бота (обычная, без сложных коннекторов)
    bot = Bot(
        token=config.TELEGRAM_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    
    # Подключение к БД
    if config.DATABASE_URL:
        try:
            await db.connect()
            print("✅ База данных подключена")
        except Exception as e:
            print(f"❌ Ошибка БД: {e}")
            print("⚠️ Бот работает без памяти")
    
    # Запуск поллинга
    print("📡 Поллинг запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
