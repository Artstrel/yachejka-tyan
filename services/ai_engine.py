import logging
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from config import GEMINI_API_KEY

# Инициализация
genai.configure(api_key=GEMINI_API_KEY)

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash", 
    safety_settings=safety_settings,
    generation_config={
        "temperature": 1.1,
        "max_output_tokens": 400, # Увеличено, чтобы не обрезать русские слова
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
    # Берем только последние 6-8 сообщений. Этого хватит для контекста разговора.
    history_rows = await db.get_context(chat_id)
    system_instruction = PERSONA
    
    # Адаптивная краткость (смягченная)
    median_len = await db.get_median_length(chat_id)
    if median_len <= 40:
        system_instruction += "\nИНСТРУКЦИЯ: Пиши максимально лаконично, одной фразой."

# Убираем слово SYSTEM, модель поймет инструкцию и так.
    # Убираем скобки и role_prefix, если они не критичны для сценария.
    context_str = f"{system_instruction}\n\n" 
    
    for row in history_rows:
        # Формат "Имя: текст" самый экономный и понятный для модели
        context_str += f"{row['user_name']}: {row['content']}\n"
    
    # Добавляем разделитель для четкости, но экономим слова
    context_str += f"\nUser: {current_message}\nBot:"

    try:
        if image_data:
            response = await model.generate_content_async([context_str, image_data])
        else:
            response = await model.generate_content_async(context_str)
            
        if not response.candidates:
            logging.error(f"Gemini пуст. Причина: {response.prompt_feedback}")
            return None # Молчим, если ответ заблокирован или пуст

        # Проверяем причину завершения
        finish_reason = response.candidates[0].finish_reason
        if finish_reason == 2: # 2 — это FINISH_REASON_MAX_TOKENS
            logging.warning(f"⚠️ Токены закончились для чата {chat_id}. Бот уходит в режим молчания.")
            return None # Просто возвращаем None вместо текста

        return response.text
    except Exception as e:
        logging.error(f"❌ Gemini Error: {e}", exc_info=True)
        return None # Молчим при критической ошибке
            
        return text_reply

    except Exception as e:
        logging.error(f"❌ Gemini Error: {e}", exc_info=True)
        return "Мои нейроны закоротило..."
