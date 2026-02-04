import os
import asyncio
import logging
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === БЕЗОПАСНЫЙ ИМПОРТ КЛЮЧЕЙ ===
# Теперь ключи берутся из "сейфа" сервера, а не из файла
TELEGRAM_TOKEN = os.getenv("8474625486:AAGoQYG3Taswf3InQdR1eqmaj7GpHLv9Nh0")
GEMINI_API_KEY = os.getenv("AIzaSyCDY0660_UKWFB2hEN1WOSjh-ZHqtMN8Z4")

# Проверка, чтобы не забыть
if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    print("❌ ОШИБКА: Ключи не найдены! Проверьте переменные окружения.")
    exit()

# ==========================================
# ⚙️ НАСТРОЙКИ (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ)
# ==========================================

# 2. Настройки персоналии (Мозг бота)
BOT_PERSONA = """
ТЫ: Аниме девочка-маскот с розовыми волосами в костюме горничной. 
ТВОЯ ЗАДАЧА: Отвечать участникам чата, помогать им, модерировать чат, но делать это с сарказмом.
СТИЛЬ: 
- Используй сленг.
- Ты любишь печеньки, сигареты "Чапман" и Фридриха (Твоего кота).
- Не будь душной. Отвечай коротко и смешно.
"""

# 3. Настройки поведения
HISTORY_LENGTH = 30  # Сколько последних сообщений помнить
RANDOM_REPLY_CHANCE = 0.05  # Вероятность (0.05 = 5%), что бот ответит на случайное сообщение сам

# ==========================================
# 🛠 ТЕХНИЧЕСКАЯ ЧАСТЬ (МОЖНО НЕ ТРОГАТЬ)
# ==========================================

# Логирование (чтобы видеть ошибки в консоли)
logging.basicConfig(level=logging.INFO)

# Инициализация Gemini
genai.configure(api_key=GEMINI_API_KEY)

# Снимаем ограничения безопасности (чтобы бот не был "душнилой")
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# Создаем модель
model = genai.GenerativeModel(
    model_name="gemini-3-flash-preview",
    safety_settings=safety_settings,
    system_instruction=BOT_PERSONA,
    generation_config={"temperature": 1.0} # Высокая температура для креативности
)

# Инициализация бота
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Словарь для хранения истории разных чатов
# Формат: {chat_id: deque([msg1, msg2...], maxlen=N)}
chats_history = {}

def update_history(chat_id, user_name, text):
    """Добавляет сообщение в историю конкретного чата"""
    if chat_id not in chats_history:
        chats_history[chat_id] = deque(maxlen=HISTORY_LENGTH)
    chats_history[chat_id].append(f"{user_name}: {text}")

async def get_gemini_response(chat_id):
    """Отправляет историю чата в Gemini и получает ответ"""
    history_text = "\n".join(chats_history[chat_id])
    try:
        # Отправляем запрос. Используем generate_content, так как историю мы собрали сами вручную
        response = await model.generate_content_async(history_text)
        return response.text
    except Exception as e:
        logging.error(f"Ошибка Gemini: {e}")
        return "Что-то мои нейроны закоротило... (Ошибка API)"

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message()
async def handler(message: types.Message):
    # Игнорируем сообщения без текста (картинки, стикеры)
    if not message.text:
        return

    # Получаем информацию о боте (чтобы узнать свой username)
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    # 1. Сохраняем сообщение в историю
    update_history(message.chat.id, message.from_user.first_name, message.text)

    # 2. Проверяем, нужно ли отвечать
    # Условия:
    # - Это личное сообщение (private)
    # - Бот упомянут (@botname)
    # - Это ответ (reply) на сообщение бота
    
    is_private = message.chat.type == 'private'
    is_mentioned = f"@{bot_username}" in message.text
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
    
    should_reply = is_private or is_mentioned or is_reply

    # 3. Случайное вмешательство (если не триггернуло выше)
    import random
    if not should_reply and random.random() < RANDOM_REPLY_CHANCE:
        should_reply = True

    # 4. Если решили отвечать — генерируем и шлем
    if should_reply:
        # Показываем статус "печатает..."
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        # Получаем ответ от ИИ
        ai_reply = await get_gemini_response(message.chat.id)
        
        # Отправляем в чат (используем Markdown для красоты, если ИИ его сгенерировал)
        try:
            await message.reply(ai_reply, parse_mode=ParseMode.MARKDOWN)
        except:
            # Если Markdown сломался, отправляем как простой текст
            await message.reply(ai_reply)

        # Добавляем и СВОЙ ответ в историю, чтобы бот помнил, что он сказал
        update_history(message.chat.id, "БОТ (ТЫ)", ai_reply)

# --- ЗАПУСК ---
async def main():
    print("Бот запущен! Нажмите Ctrl+C для выхода.")
    # Удаляем вебхуки и запускаем опрос
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")