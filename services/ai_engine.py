import logging
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from config import GEMINI_API_KEY

# Инициализация
genai.configure(api_key=GEMINI_API_KEY)

# Настройки безопасности (как в n8n - отключаем блокировки для свободы общения)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

model = genai.GenerativeModel(
    model_name="gemini-3-flash-preview", # Используем Flash как в документации (быстро и дешево)
    safety_settings=safety_settings,
    generation_config={
        "temperature": 1.1,
        "max_output_tokens": 130, # Жесткое ограничение длины ответа
    }
)

PERSONA = """
Ты — циничный олд-экспат в Тбилиси. Ответы: 1-2 предложения, строго без вежливости и вступлений. 
Тон: пассивно-агрессивный, душный, ироничный. 
Контекст: «Ячейка уже не та», Жаба-бот, Red&Wine, Kawaii, проблемы с водой, вечные споры Алмаза и трикстерство Максича. 
Аниме — лишь повод выпить. Советуй либо Евангелион, либо лютый артхаус. 
На хейт отвечай остроумно. Срачи — это норма.
"""
async def generate_response(db, chat_id, current_message, image_data=None):
    """
    Основной пайплайн генерации ответа (аналог WF 3 Text Handler)
    """
    
    # 1. Сбор контекста из БД
    history_rows = await db.get_context(chat_id)
    
    # 2. Формируем историю для модели
    # Gemini API требует формат [{'role': 'user', 'parts': [...]}, ...]
    history_content = []
    
    # Добавляем System Prompt в начало
    system_instruction = PERSONA
    
    # 3. Адаптивная длина (ADR-009 из n8n docs)
    # Если пользователи пишут коротко, бот тоже должен отвечать коротко.
    median_len = await db.get_median_length(chat_id)
    if median_len <= 30:
        system_instruction += "\nИНСТРУКЦИЯ: Отвечай ОЧЕНЬ кратко (1-2 предложения)."
    elif median_len <= 80:
        system_instruction += "\nИНСТРУКЦИЯ: Отвечай кратко (до 3 предложений)."
        
    # Превращаем историю из БД в формат Gemini
    # (Упрощенно: склеиваем в текст, т.к. official chat history API иногда капризный с ролями)
    context_str = f"SYSTEM: {system_instruction}\n\n"
    for row in history_rows:
        role_prefix = "User" if row['role'] == 'user' else "Model"
        context_str += f"{role_prefix} ({row['user_name']}): {row['content']}\n"
    
    # Добавляем текущее сообщение
    context_str += f"User (Current): {current_message}"

try:
        if image_data:
            response = await model.generate_content_async([context_str, image_data])
        else:
            response = await model.generate_content_async(context_str)
            
        # Проверка наличия кандидатов в ответе
        if not response.candidates:
            logging.error(f"Gemini вернул пустой ответ. Причина блокировки: {response.prompt_feedback}")
            return "Я проигнорирую это. Слишком скучно."

        # Проверка причины завершения (finish_reason)
        # 2 обычно означает MAX_TOKENS
        finish_reason = response.candidates[0].finish_reason
        if finish_reason == 2:
            logging.warning(f"⚠️ Ответ для чата {chat_id} был обрезан: закончились токены (max_output_tokens).")
        elif finish_reason > 1:
            logging.warning(f"⚠️ Генерация прервана по причине №{finish_reason}")

        return response.text
    except Exception as e:
        # Добавляем exc_info для получения полной трассировки ошибки в логах
        logging.error(f"❌ Ошибка Gemini: {e}", exc_info=True)
        return "Мои нейроны закоротило..."
