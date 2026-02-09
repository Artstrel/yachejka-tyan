import logging
import base64
import io
import asyncio
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY

# Инициализация клиента
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Список моделей по приоритету
# (name: ID модели, vision: поддерживает ли картинки)
MODELS = [
    # 1. Основная: Gemini 2.0 Flash Lite (Быстрая, видит картинки, бесплатно)
    {"name": "google/gemini-2.0-flash-lite-preview-02-05:free", "vision": True},
    
    # 2. Резерв 1: Gemini 2.0 Pro (Умная, видит картинки, бесплатно, но могут быть лимиты)
    {"name": "google/gemini-2.0-pro-exp-02-05:free", "vision": True},
    
    # 3. Резерв 2: Qwen 2.5 72B (Мощный текст, понимает русский лучше всех, бесплатно)
    {"name": "qwen/qwen-2.5-72b-instruct:free", "vision": False},
    
    # 4. Резерв 3: Llama 3.3 70B (Классика, надежная, бесплатно)
    {"name": "meta-llama/llama-3.3-70b-instruct:free", "vision": False},
    
    # 5. Последний шанс: Mistral Nemo (Маленькая, но очень стабильная)
    {"name": "mistralai/mistral-nemo:free", "vision": False},
]

PERSONA = """
Ты — циничный олд-экспат в Тбилиси. Ответы: 1-2 предложения, строго без вежливости и вступлений. 
Тон: пассивно-агрессивный, душный, ироничный. 
Контекст: «Ячейка уже не та», Жаба-бот, Red&Wine, Kawaii, проблемы с водой, вечные споры Алмаза и трикстерство Максича. 
Аниме — лишь повод выпить. Советуй либо Евангелион, либо лютый артхаус. 
На хейт отвечай остроумно. Срачи — это норма.
"""

async def generate_response(db, chat_id, current_message, image_data=None):
    # Получаем контекст один раз для всех попыток
    history_rows = await db.get_context(chat_id)
    median_len = await db.get_median_length(chat_id)

    # Подготовка картинки (если есть)
    img_b64 = None
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        except Exception as e:
            logging.error(f"⚠️ Ошибка обработки картинки: {e}")

    # Перебираем модели по очереди
    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        supports_vision = model_cfg["vision"]

        try:
            # logging.info(f"🔄 Пробую модель: {model_name}...") # Раскомментируй для отладки

            messages = []
            
            # Настройка персоны
            sys_msg = PERSONA
            if median_len <= 40:
                sys_msg += "\nИНСТРУКЦИЯ: Пиши максимально лаконично, одной фразой."
            messages.append({"role": "system", "content": sys_msg})

            # Добавляем историю
            for row in history_rows:
                role = "assistant" if row['role'] == "model" else "user"
                messages.append({"role": role, "content": row['content']})

            # Формируем текущее сообщение
            user_content = []
            
            # Текст сообщения
            text_part = current_message
            if image_data and not supports_vision:
                text_part += " [Пользователь прикрепил изображение, но я его не вижу. Если спросят — отшутись или придумай, что там.]"
            
            user_content.append({"type": "text", "text": text_part})

            # Картинка (только для Vision моделей)
            if image_data and supports_vision and img_b64:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })

            messages.append({"role": "user", "content": user_content})

            # Делаем запрос
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.7,
                max_tokens=600,
                extra_headers={
                    "HTTP-Referer": "https://telegram.org",
                    "X-Title": "Yachejka Bot"
                }
            )

            if response.choices and response.choices[0].message.content:
                # Успех! Возвращаем ответ
                logging.info(f"✅ Успешный ответ от {model_name}")
                return response.choices[0].message.content

        except Exception as e:
            logging.warning(f"⚠️ Ошибка модели {model_name}: {e}")
            # Если ошибка — просто идем к следующей модели в цикле
            continue

    # Если все модели упали
    logging.error("❌ ВСЕ модели недоступны")
    return None
