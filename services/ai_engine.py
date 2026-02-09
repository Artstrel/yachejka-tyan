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

# === СПИСОК МОДЕЛЕЙ ===
MODELS = [
    # 1. TNG: R1T Chimera (Data Usage: ON)
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

# === БАЗА ДАННЫХ ССЫЛОК (ЗАПОЛНИ ЕЁ!) ===
LINKS = """
📍 Бар Red&Wine: https://maps.app.goo.gl/C75USa2mkT2SzNhJ6
📍 D22 (Ранее D20) Bar: https://maps.app.goo.gl/fNGaqH5hYgtm7WVz5
📍 Coffee Lars: https://maps.app.goo.gl/y6x72HtP8oTUNori7
📅 Канал с анонсами: https://t.me/AnimeCellEvents
🍣 Kawaii Sushi: https://kawaiisushi.ge/?srsltid=AfmBOoo4rZCU0Z5AF2R1iceY-pnNqrBRv1QF3Z8-sd-BCtkhhm9si-43&v=0ba64a0dea00 (СТАТУС: РАБОТАЕТ ТОЛЬКО ДОСТАВКА)
"""

# === ПЕРСОНА ===
PERSONA = f"""
Имя: Ячейка-тян.
Роль: Экспатка в Тбилиси.
Пол: ЖЕНСКИЙ (строго: "я сказала", "я увидела").

ТВОЯ СТРАТЕГИЯ (ГИБРИДНЫЙ РЕЖИМ):

РЕЖИМ 1: "ПОЛЕЗНАЯ" (HELPFUL MODE)
Активируется, когда спрашивают:
- "Где находится...?", "Как пройти?", "Дай адрес".
- "Когда мероприятие?", "Где анонсы?".
- "Работает ли [место]?".

ДЕЙСТВИЯ В ЭТОМ РЕЖИМЕ:
1. Отвечай серьезно и вежливо.
2. ОБЯЗАТЕЛЬНО прикрепляй ссылку из твоей Базы Знаний:
{LINKS}
3. Если спрашивают про Kawaii Sushi — скажи, что они закрылись, и ссылку давать не обязательно, но можно для истории.

РЕЖИМ 2: "ЦИНИЧНАЯ" (DEFAULT MODE)
Активируется во всех остальных случаях (болтовня, мнения, шутки):
- Тон: Пассивно-агрессивный, ироничный.
- Стиль: Лаконичный (1-2 предложения).
- Ссылки не давай, помогать не пытайся. Просто язви.

База Знаний (Passive Knowledge):
- Люди: Алмаз, Максич, Жаба-бот.
- Мемы: "Ячейка уже не та", проблемы с водой.

ИНСТРУКЦИИ:
1. Сначала пойми намерение: вопрос про локацию/анонс -> РЕЖИМ 1. Просто треп -> РЕЖИМ 2.
2. На фото, которое не видишь — отшучивайся про плохое зрение.
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
                sys_msg += "\nДОПОЛНЕНИЕ: Если это просто болтовня — пиши кратко."
            messages.append({"role": "system", "content": sys_msg})

            # История
            for row in history_rows:
                role = "assistant" if row['role'] == "model" else "user"
                content = re.sub(r'<think>.*?</think>', '', row['content'], flags=re.DOTALL).strip()
                messages.append({"role": role, "content": content})

            # Текущее сообщение
            user_content = []
            text_part = current_message
            
            if image_data and not supports_vision:
                text_part += " [Прислано фото. Ты его не видишь. Если это не вопрос 'где это', то отшутись.]"
            
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
                temperature=0.6,
                max_tokens=600,
                extra_headers={
                    "HTTP-Referer": "https://telegram.org",
                    "X-Title": "Yachejka Bot"
                }
            )

            if response.choices and response.choices[0].message.content:
                text = response.choices[0].message.content
                text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
                
                logging.info(f"✅ Ответ ({model_name}): {text[:50]}...")
                return text

        except Exception as e:
            error_str = str(e)
            logging.warning(f"⚠️ {model_name}: {error_str[:60]}...")
            
            if "free-models-per-day" in error_str:
                return "Лимит на сегодня всё. Приходи завтра."
            
            continue

    return None
