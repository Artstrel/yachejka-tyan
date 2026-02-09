import logging
import base64
import io
import re
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY

# Инициализация клиента OpenRouter
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Slug модели на OpenRouter
MODEL_NAME = "tngtech/deepseek-r1t2-chimera"

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
    
    # Формируем историю сообщений
    messages = [{"role": "system", "content": PERSONA}]
    
    # Адаптивная краткость (если нужно)
    median_len = await db.get_median_length(chat_id)
    if median_len <= 40:
        messages[0]["content"] += "\nИНСТРУКЦИЯ: Пиши максимально лаконично, одной фразой."

    # Добавляем историю из БД
    for row in history_rows:
        # OpenRouter/OpenAI используют роли 'user' и 'assistant'
        role = "assistant" if row['role'] == "model" else "user"
        content = f"{row['user_name']}: {row['content']}"
        messages.append({"role": role, "content": content})

    # Формируем текущее сообщение пользователя (Text + Image)
    user_content = [{"type": "text", "text": current_message}]

    if image_data:
        try:
            # Конвертируем PIL Image в base64
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}"
                }
            })
        except Exception as e:
            logging.warning(f"⚠️ Ошибка обработки изображения: {e}")

    messages.append({"role": "user", "content": user_content})

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            # Температура 0.6-0.7 хороша для R1, чтобы не уходить в бред, но сохранить стиль
            temperature=0.7,
            max_tokens=1024,
            extra_headers={
                "HTTP-Referer": "https://telegram.org",
                "X-Title": "Yachejka Bot"
            }
        )
        
        if not response.choices:
            return None

        text = response.choices[0].message.content
        
        # ВАЖНО: Удаляем блок мыслей <think>...</think>, свойственный R1 моделям
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        
        if not text:
            logging.warning(f"Пустой ответ после удаления <think> для {chat_id}")
            return None 

        return text

    except Exception as e:
        logging.error(f"❌ OpenRouter Error: {e}")
        return None
