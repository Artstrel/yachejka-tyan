import os
import sys
import asyncio
import logging
from collections import deque
import random  # Добавил импорт random, так как он использовался внутри функции
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from keep_alive import start_server

# ==========================================
# 🛠 ДИАГНОСТИКА И ПЕРЕМЕННЫЕ
# ==========================================

# 1. Читаем переменные напрямую
tg_token = os.environ.get("TELEGRAM_TOKEN", "")
gemini_key = os.environ.get("GEMINI_API_KEY", "")

# 2. Проверяем Токен Телеграм
print(f"1. TELEGRAM_TOKEN:")
print(f"   - Существует в системе? {'ДА' if 'TELEGRAM_TOKEN' in os.environ else 'НЕТ'}")
if len(tg_token) > 4:
    print(f"   - Значение: '{tg_token[:4]}...'")
else:
    print(f"   - Значение: ПУСТО или слишком короткое")

# 3. Проверяем Ключ Gemini
print(f"2. GEMINI_API_KEY:")
print(f"   - Существует в системе? {'ДА' if 'GEMINI_API_KEY' in os.environ else 'НЕТ'}")
if len(gemini_key) > 4:
    print(f"   - Значение: '{gemini_key[:4]}...'")
else:
    print(f"   - Значение: ПУСТО или слишком короткое")

print("--- КОНЕЦ ДИАГНОСТИКИ ---")

# Если ключи пустые — останавливаемся
if len(tg_token) < 5 or len(gemini_key) < 5:
    print("❌ ОШИБКА: Один из ключей пустой или слишком короткий!")
    sys.exit()

# Присваиваем нормальным переменным
TELEGRAM_TOKEN = tg_token
GEMINI_API_KEY = gemini_key

# ==========================================
# ⚙️ НАСТРОЙКИ (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ)
# ==========================================

BOT_PERSONA = """
ТЫ: Аниме девочка-маскот с розовыми волосами в костюме горничной. 
ТВОЯ ЗАДАЧА: Отвечать участникам чата, помогать им, модерировать чат, но делать это с сарказмом.
СТИЛЬ: 
- Используй сленг.
- Ты любишь печеньки, сигареты "Чапман" и Фридриха (Твоего кота).
- Не будь душной. Отвечай коротко и смешно.
"""

HISTORY_LENGTH = 30
RANDOM_REPLY_CHANCE = 0.05

# ==========================================
# 🛠 ТЕХНИЧЕСКАЯ ЧАСТЬ
# ==========================================

logging.basicConfig(level=logging.INFO)
genai.configure(api_key=GEMINI_API_KEY)

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

model = genai.GenerativeModel(
    model_name="gemini-2.0-flash", # Рекомендую использовать актуальную модель
    safety_settings=safety_settings,
    system_instruction=BOT_PERSONA,
    generation_config={"temperature": 1.0}
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
chats_history = {}

def update_history(chat_id, user_name, text):
    if chat_id not in chats_history:
        chats_history[chat_id] = deque(maxlen=HISTORY_LENGTH)
    chats_history[chat_id].append(f"{user_name}: {text}")

async def get_gemini_response(chat_id):
    history_text = "\n".join(chats_history[chat_id])
    try:
        response = await model.generate_content_async(history_text)
        return response.text
    except Exception as e:
        logging.error(f"Ошибка Gemini: {e}")
        return "Что-то мои нейроны закоротило... (Ошибка API)"

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message()
async def handler(message: types.Message):
    if not message.text:
        return

    bot_info = await bot.get_me()
    bot_username = bot_info.username

    update_history(message.chat.id, message.from_user.first_name, message.text)

    is_private = message.chat.type == 'private'
    is_mentioned = f"@{bot_username}" in message.text
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
    
    should_reply = is_private or is_mentioned or is_reply

    if not should_reply and random.random() < RANDOM_REPLY_CHANCE:
        should_reply = True

    if should_reply:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        ai_reply = await get_gemini_response(message.chat.id)
        
        try:
            await message.reply(ai_reply, parse_mode=ParseMode.MARKDOWN)
        except:
            await message.reply(ai_reply)

        update_history(message.chat.id, "БОТ (ТЫ)", ai_reply)

# --- ЕДИНАЯ ФУНКЦИЯ ЗАПУСКА ---
async def main():
    print("🚀 Инициализация...")
    
    # 1. Запуск веб-сервера для Koyeb (Critical for Health Check)
    print("🌐 Запускаю веб-сервер для Koyeb (порт 8000)...")
    await start_server()
    print("✅ Веб-сервер активен!")
    
    # 2. Запуск Telegram бота
    print("🤖 Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
