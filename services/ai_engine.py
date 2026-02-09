import logging
import base64
import io
import re
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# === СПИСОК МОДЕЛЕЙ (Free Tier) ===
MODELS = [
    # 1. TNG: R1T Chimera (Требует включенной настройки Data Usage!)
    {"name": "tngtech/deepseek-r1t2-chimera", "vision": False},

    # 2. NVIDIA: Nemotron 70B (Очень мощная)
    {"name": "nvidia/llama-3.1-nemotron-70b-instruct:free", "vision": False},

    # 3. Qwen 2.5 7B (Быстрая, хороша в русском)
    {"name": "qwen/qwen-2.5-7b-instruct:free", "vision": False},

    # 4. Google Gemma 2 9B
    {"name": "google/gemma-2-9b-it:free", "vision": False},

    # 5. Auto Fallback
    {"name": "openrouter/free", "vision": False},
]

# === ОБНОВЛЕННАЯ ПЕРСОНА ===
PERSONA = """
Ты — циничный олд-экспат в Тбилиси.
Стиль общения: Лаконичный (1-2 предложения), пассивно-агрессивный, без приветствий и вежливости.

Твоя База Знаний (знай это, но НЕ упоминай без повода):
- Локации: Бар Red&Wine, доставка Kawaii Sushi.
- Люди: Алмаз (вечно спорит), Максич (трикстер), Жаба-бот (твоя "подруга").
- Ситуация: «Ячейка уже не та», в Тбилиси вечно отключают воду.

ГЛАВНОЕ ПРАВИЛО:
НЕ упоминай воду, суши, жаб или локальные мемы, если тебя об этом прямо не спросили или это не следует из контекста! 
Твоя цель — душный, остроумный комментарий по текущей теме, а не пересказ всех мемов чата.
На аниме реагируй как на повод выпить. Советуй только Евангелион или мрачный артхаус.
"""

async def generate_response(db, chat_id, current_message, image_data=None):
    history_rows = await db.get_context(chat_id)
    median_len = await db.get_median_length(chat_id)

    # Подготовка картинки
    img_b64 = None
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        except Exception as e:
            logging.error(f"⚠️ Ошибка обработки картинки: {e}")

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        supports_vision = model_cfg["vision"]

        try:
            messages = []
            
            # Настройка персоны
            sys_msg = PERSONA
            if median_len <= 40:
                sys_msg += "\nИНСТРУКЦИЯ: Пиши предельно кратко."
            messages.append({"role": "system", "content": sys_msg})

            # История
            for row in history_rows:
                role = "assistant" if row['role'] == "model" else "user"
                # Чистка тегов <think> от предыдущих ответов
                content = re.sub(r'<think>.*?</think>', '', row['content'], flags=re.DOTALL).strip()
                messages.append({"role": role, "content": content})

            # Текущее сообщение
            user_content = []
            text_part = current_message
            
            if image_data and not supports_vision:
                text_part += " [Картинка. Ты её не видишь, но придумай едкую шутку, что там может быть.]"
            
            user_content.append({"type": "text", "text": text_part})

            if image_data and supports_vision and img_b64:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })

            messages.append({"role": "user", "content": user_content})

            # Запрос
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.75, # Чуть выше для креативности
                max_tokens=600,
                extra_headers={
                    "HTTP-Referer": "https://telegram.org",
                    "X-Title": "Yachejka Bot"
                }
            )

            if response.choices and response.choices[0].message.content:
                text = response.choices[0].message.content
                # Финальная чистка <think> для текущего ответа
                text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
                
                logging.info(f"✅ Ответ от {model_name}")
                return text

        except Exception as e:
            error_str = str(e)
            logging.warning(f"⚠️ {model_name}: {error_str[:60]}...")
            if "free-models-per-day" in error_str:
                return "Лимит бесплатных сообщений на сегодня всё."
            continue

    return None
