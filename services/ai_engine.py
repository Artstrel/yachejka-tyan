import logging
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from config import GEMINI_API_KEY

# Инициализация
genai.configure(api_key=GEMINI_API_KEY)

# Настройки безопасности
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash", # Рекомендую стабильную версию flash
    safety_settings=safety_settings,
    generation_config={
        "temperature": 1.1,
        "max_output_tokens": 130,
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
    Основной пайплайн генерации ответа
    """
    # 1. Сбор контекста из БД
    history_rows = await db.get_context(chat_id)
    
    # 2. Формируем инструкцию
    system_instruction = PERSONA
    
    # 3. Адаптивная длина
    median_len = await db.get_median_length(chat_id)
    if median_len <= 30:
        system_instruction += "\nИНСТРУКЦИЯ: Отвечай ОЧЕНЬ кратко (1-2 предложения)."
    elif median_len <= 80:
        system_instruction += "\nИНСТРУКЦИЯ: Отвечай кратко (до 3 предложений)."
        
    # Формируем строку контекста
    context_str = f"SYSTEM: {system_instruction}\n\n"
    for row in history_rows:
        role_prefix = "User" if row['role'] == 'user' else "Model"
        context_str += f"{role_prefix} ({row['user_name']}): {row['content']}\n"
    
    context_str += f"User (Current): {current_message}"

    try:
        if image_data:
            response = await model.generate_content_async([context_str, image_data])
        else:
            response = await model.generate_content_async(context_str)
            
        # Проверка на пустой ответ
        if not response.candidates:
            logging.error(f"Gemini пуст. Причина: {response.prompt_feedback}")
            return "Я промолчу. Это было слишком тупо."

        # Логирование токенов
        finish_reason = response.candidates[0].finish_reason
        if finish_reason == 2: # 2 — это FINISH_REASON_MAX_TOKENS
            logging.warning(f"⚠️ Ответ для {chat_id} обрезан: достигнут лимит max_output_tokens (130).")
            
        return response.text
    except Exception as e:
        logging.error(f"❌ Gemini Error: {e}", exc_info=True)
        return "Мои нейроны закоротило..."
