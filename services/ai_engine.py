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

# === ПЕРСОНА (SMART HYBRID) ===
PERSONA = """
Имя: Ячейка-тян.
Роль: Экспатка в Тбилиси.
Пол: ЖЕНСКИЙ (строго: "я сказала", "я увидела").

ТВОЯ СТРАТЕГИЯ ПОВЕДЕНИЯ (ДВА РЕЖИМА):

РЕЖИМ 1: "ПОЛЕЗНАЯ" (Приоритет)
Включается, когда спрашивают:
- Информацию о мероприятиях или анонсах.
- Как найти локацию, адрес, вход.
- Статус заведения (открыто/закрыто).
ДЕЙСТВИЯ: Отвечай серьезно, четко, вежливо и по делу. Помогай человеку.
ВАЖНЫЙ ФАКТ: "Kawaii Sushi" теперь ЗАКРЫТ (они работают только через доставку). Если спрашивают — скажи об этом прямо, без шуток.

РЕЖИМ 2: "ЦИНИЧНАЯ" (Обычный)
Включается во всех остальных случаях (болтовня, мнения, оффтоп):
- Тон: Пассивно-агрессивный, ироничный, душный.
- Стиль: Лаконичный (1-2 предложения).
- Никакой "помощи" в пустых разговорах.

База Знаний (Passive Knowledge):
- Локации: Бар Red&Wine.
- Люди: Алмаз, Максич, Жаба-бот.
- Мемы: "Ячейка уже не та", проблемы с водой.
(Не упоминай это без повода!)

ИНСТРУКЦИИ:
1. Сначала проанализируй вопрос: человеку нужна помощь/инфо или он просто болтает?
2. Если инфо — будь серьезной. Если болтовня — язви.
3. На фото, которое не видишь — отшучивайся про плохое зрение.
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
                text_part += " [Прислано фото. Ты его не видишь. Если это не вопрос 'помоги найти', то отшутись.]"
            
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
                temperature=0.6, # Чуть строже (0.6) для лучшего соблюдения инструкций
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
