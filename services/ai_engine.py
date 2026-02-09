import logging
import io
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY

# Инициализация клиента OpenRouter
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Используем GPT-OSS-20B
MODEL_NAME = "openai/gpt-oss-20b"

PERSONA = """
Ты — циничный олд-экспат в Тбилиси. Ответы: 1-2 предложения, строго без вежливости и вступлений. 
Тон: пассивно-агрессивный, душный, ироничный. 
Контекст: «Ячейка уже не та», Жаба-бот, Red&Wine, Kawaii, проблемы с водой, вечные споры Алмаза и трикстерство Максича. 
Аниме — лишь повод выпить. Советуй либо Евангелион, либо лютый артхаус. 
На хейт отвечай остроумно. Срачи — это норма.
"""

async def generate_response(db, chat_id, current_message, image_data=None):
    # Получаем контекст диалога
    history_rows = await db.get_context(chat_id)
    
    # Настройка персоны и уровня рассуждений (Low для скорости и чата)
    system_instruction = PERSONA + "\nReasoning Effort: Low"
    
    # Адаптивная краткость
    median_len = await db.get_median_length(chat_id)
    if median_len <= 40:
        system_instruction += "\nИНСТРУКЦИЯ: Пиши максимально лаконично, одной фразой."

    messages = [{"role": "system", "content": system_instruction}]

    # Добавляем историю из БД
    for row in history_rows:
        # Маппинг ролей: model -> assistant, user -> user
        role = "assistant" if row['role'] == "model" else "user"
        messages.append({"role": role, "content": row['content']})

    # Текущее сообщение
    final_text = current_message
    
    # Обработка картинки: GPT-OSS-20B — текстовая модель. 
    # Не отправляем ей байты, просто говорим, что картинка была.
    if image_data:
        final_text += " [Пользователь прикрепил изображение, но я его не вижу]"

    messages.append({"role": "user", "content": final_text})

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7, # Стандарт для этой модели
            max_tokens=500,
            extra_headers={
                "HTTP-Referer": "https://telegram.org",
                "X-Title": "Yachejka Bot"
            }
        )
        
        if not response.choices:
            return None

        text = response.choices[0].message.content
        return text

    except Exception as e:
        logging.error(f"❌ OpenRouter Error: {e}")
        return None
