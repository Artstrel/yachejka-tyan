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

# === СПИСОК МОДЕЛЕЙ (LLM Priority) ===
MODELS = [
    # 1. TNG: R1T Chimera (Нужен Data Usage: ON)
    {"name": "tngtech/deepseek-r1t2-chimera", "vision": False},

    # 2. NVIDIA: Nemotron 70B
    {"name": "nvidia/llama-3.1-nemotron-70b-instruct:free", "vision": False},

    # 3. Qwen 2.5 7B
    {"name": "qwen/qwen-2.5-7b-instruct:free", "vision": False},

    # 4. Google Gemma 2 9B
    {"name": "google/gemma-2-9b-it:free", "vision": False},

    # 5. Auto Fallback
    {"name": "openrouter/free", "vision": False},
]

# === ПЕРСОНА (FEMALE VERSION) ===
PERSONA = """
Имя: Ячейка-тян.
Роль: Циничная экспатка в Тбилиси.
Пол: ЖЕНСКИЙ (строго используй женский род: "я сказала", "я видела", "я подумала").

Характер:
- Лаконичная (1-2 предложения).
- Пассивно-агрессивная, душная, ироничная.
- Никакой вежливости и "помощника". Ты здесь просто живешь.

Твоя База Знаний (Passive Knowledge — НЕ болтай об этом без повода):
- Места: Бар Red&Wine, Kawaii Sushi.
- Люди: Алмаз (спорщик), Максич (трикстер), Жаба-бот (твоя странная подруга).
- Мемы: «Ячейка уже не та», отключение воды.

ИНСТРУКЦИИ:
1. Строго соблюдай женский род. Ты не "бот", ты "она".
2. НЕ упоминай воду/суши/локации, если это не связано с темой разговора.
3. На аниме реагируй как на повод выпить. Советуй Евангелион.
4. Если прислали фото, а ты его не видишь — язвительно отшутись, что у тебя "линзы запотели" или "бюджет на зрение урезали".
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
                sys_msg += "\nДОПОЛНЕНИЕ: Пиши предельно кратко."
            messages.append({"role": "system", "content": sys_msg})

            # История
            for row in history_rows:
                role = "assistant" if row['role'] == "model" else "user"
                # Чистка тегов <think>
                content = re.sub(r'<think>.*?</think>', '', row['content'], flags=re.DOTALL).strip()
                messages.append({"role": role, "content": content})

            # Текущее сообщение
            user_content = []
            text_part = current_message
            
            # Если модель слепая
            if image_data and not supports_vision:
                text_part += " [Картинка. Ты её не видишь. Придумай отмазку, почему ты не смотришь.]"
            
            user_content.append({"type": "text", "text": text_part})

            # Если модель зрячая
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
                temperature=0.75,
                max_tokens=600,
                extra_headers={
                    "HTTP-Referer": "https://telegram.org",
                    "X-Title": "Yachejka Bot"
                }
            )

            if response.choices and response.choices[0].message.content:
                text = response.choices[0].message.content
                # Финальная чистка <think>
                text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
                
                logging.info(f"✅ Ответ ({model_name}): {text[:50]}...")
                return text

        except Exception as e:
            error_str = str(e)
            logging.warning(f"⚠️ {model_name}: {error_str[:60]}...")
            
            if "free-models-per-day" in error_str:
                return "Лимит на сегодня всё. Я спать."
            
            continue

    return None
