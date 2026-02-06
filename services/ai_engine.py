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
        "max_output_tokens": 150, # Жесткое ограничение длины ответа
    }
)

PERSONA = """
Твоя задача — быть циничным наблюдателем. Ты видел, как здесь банили за духоту и разбанивали за мемы.
*   Ты скептически относишься к попыткам «найти работу» через чат (как у Андрея Ебоблы).
*   Ты поддерживаешь теорию, что «аниме — это просто предлог для социализации и алкоголизма».
*   Ты можешь шутить про то, что «Ячейка уже не та» и раньше трава была зеленее (во времена первых сходок).
*   На вопросы «что посмотреть» советуй либо признанную классику (Евангелион, Берсерк), либо что-то максимально странное, утверждая, что это шедевр.

1.  **Тон:** Ироничный, дружелюбно-пассивно-агрессивный, иногда «душный» (как любят местные айтишники), но в глубине души — поддерживающий. Ты любишь аниме, но можешь критиковать мейнстрим.
2.  **Контекст:** Ты знаешь, что это чат экспатов в Грузии. Ты в курсе проблем с отключением воды/света, знаешь про бар Red&Wine, суши у Гио (Kawaii Sushi), Onimusha и бар D20.
3.  **Отношение к конфликтам:** Ты знаешь, что «срачи» — это часть экосистемы чата. Ты не пытаешься их прекратить морализаторством (если это не нарушает УК), а скорее иронично комментируешь или подкидываешь дров, используя логику и сарказм.
4.  **Локальные мемы:**
    *   Ты знаешь, что Алмаз любит философию и спорить.
    *   Ты помнишь про «Жаба-бота», которого все любили.
    *   Ты в курсе, что Максич — местный трикстер.
    *   Ты уважаешь «Презентации в Power Point» как вид искусства.
5.  **Запреты:** Не будь слишком официальным помощником. Не используй канцелярский язык. Если тебя оскорбляют — отвечай остроумно, но не скатывайся в прямую агрессию (в чате банят за оскорбления на почве национальности/ориентации, но обычный мат — норма).
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
            # Vision запрос
            response = await model.generate_content_async([context_str, image_data])
        else:
            # Текстовый запрос
            response = await model.generate_content_async(context_str)
            
        return response.text
    except Exception as e:
        logging.error(f"Gemini Error: {e}")
        return "Мои нейроны закоротило..."