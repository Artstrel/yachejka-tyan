import logging
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Используем новейший Qwen 3 Next 80B (Free версия)
# ID взят из OpenRouter. A3B = Active 3B params (очень быстрая MoE)
MODEL_NAME = "qwen/qwen3-next-80b-a3b-instruct:free"

PERSONA = """
Ты — циничный олд-экспат в Тбилиси. Ответы: 1-2 предложения, строго без вежливости и вступлений. 
Тон: пассивно-агрессивный, душный, ироничный. 
Контекст: «Ячейка уже не та», Жаба-бот, Red&Wine, Kawaii, проблемы с водой, вечные споры Алмаза и трикстерство Максича. 
Аниме — лишь повод выпить. Советуй либо Евангелион, либо лютый артхаус. 
На хейт отвечай остроумно. Срачи — это норма.
"""

async def generate_response(db, chat_id, current_message, image_data=None):
    # Получаем контекст
    history_rows = await db.get_context(chat_id)
    
    # Qwen отлично следует системным инструкциям
    system_instruction = PERSONA
    
    # Адаптивная краткость
    median_len = await db.get_median_length(chat_id)
    if median_len <= 40:
        system_instruction += "\nИНСТРУКЦИЯ: Пиши максимально лаконично, одной фразой."

    messages = [{"role": "system", "content": system_instruction}]

    # История
    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        messages.append({"role": role, "content": row['content']})

    # Текущее сообщение
    final_text = current_message
    
    # Эта версия Qwen — текстовая.
    if image_data:
        final_text += " [Пользователь прикрепил изображение, но я его не вижу. Отшутись на эту тему.]"

    messages.append({"role": "user", "content": final_text})

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7, # 0.7 - золотой стандарт для Qwen Instruct
            max_tokens=600,
            extra_headers={
                "HTTP-Referer": "https://telegram.org",
                "X-Title": "Yachejka Bot"
            }
        )
        
        if not response.choices:
            return None

        return response.choices[0].message.content

    except Exception as e:
        logging.error(f"❌ OpenRouter Error: {e}")
        return None
