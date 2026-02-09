import logging
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY

# Инициализация клиента OpenRouter
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Используем бесплатную версию GPT-OSS-120B
# Это мощная MoE модель (117B параметров), сравнимая с GPT-4o-mini/GPT-4
MODEL_NAME = "openai/gpt-oss-120b:free"

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
    
    # Настройка персоны. 
    # Reasoning Effort: Low — заставляет модель отвечать быстро, без лишних "раздумий", 
    # что идеально для чат-бота.
    system_instruction = PERSONA + "\nReasoning Effort: Low"
    
    # Адаптивная краткость
    median_len = await db.get_median_length(chat_id)
    if median_len <= 40:
        system_instruction += "\nИНСТРУКЦИЯ: Пиши максимально лаконично, одной фразой."

    messages = [{"role": "system", "content": system_instruction}]

    # Добавляем историю из БД
    for row in history_rows:
        # Маппинг ролей
        role = "assistant" if row['role'] == "model" else "user"
        messages.append({"role": role, "content": row['content']})

    # Текущее сообщение
    final_text = current_message
    
    # GPT-OSS-120B — текстовая модель (в бесплатной версии).
    # Вместо картинки отправляем описание.
    if image_data:
        final_text += " [Пользователь прикрепил изображение, но я его не вижу, так как я текстовая версия]"

    messages.append({"role": "user", "content": final_text})

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7, # 0.7 — хороший баланс для этой модели
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
        # Если бесплатная модель перегружена (частая проблема free-tier),
        # можно вернуть None, чтобы бот просто промолчал, или заглушку.
        return None
