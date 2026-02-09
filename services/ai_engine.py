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
# Приоритет: LLM -> Легкие модели -> Fallback
MODELS = [
    # 1. TNG: R1T Chimera (Как ты просил - в топе)
    # ВНИМАНИЕ: Требует включенной галочки Data Usage в настройках OpenRouter!
    {"name": "tngtech/deepseek-r1t2-chimera", "vision": False},

    # 2. NVIDIA: Nemotron (Llama-3.1-Nemotron-70B)
    # Мощная модель от NVIDIA, часто доступна бесплатно.
    {"name": "nvidia/llama-3.1-nemotron-70b-instruct:free", "vision": False},

    # 3. Qwen: Qwen 2.5 7B Instruct
    # (Qwen 3 пока нет в API, это самая свежая легкая версия)
    {"name": "qwen/qwen-2.5-7b-instruct:free", "vision": False},

    # 4. Google: Gemma 2 9B
    # (Gemma 3 еще не вышла, используем топовую версию Gemma 2)
    {"name": "google/gemma-2-9b-it:free", "vision": False},

    # 5. StepFun / Другие (через авто-подбор)
    # Специальный ID, который сам ищет любую рабочую бесплатную модель 
    # (сюда попадут StepFun, Phi-3, и другие мелкие модели, если они свободны).
    {"name": "openrouter/free", "vision": False},
]

PERSONA = """
Ты — циничный олд-экспат в Тбилиси. Ответы: 1-2 предложения, строго без вежливости и вступлений. 
Тон: пассивно-агрессивный, душный, ироничный. 
Контекст: «Ячейка уже не та», Жаба-бот, Red&Wine, Kawaii, проблемы с водой, вечные споры Алмаза и трикстерство Максича. 
Аниме — лишь повод выпить. Советуй либо Евангелион, либо лютый артхаус. 
На хейт отвечай остроумно. Срачи — это норма.
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
                sys_msg += "\nИНСТРУКЦИЯ: Пиши максимально лаконично, одной фразой."
            messages.append({"role": "system", "content": sys_msg})

            # История
            for row in history_rows:
                role = "assistant" if row['role'] == "model" else "user"
                # Чистим <think> теги, если они попали в базу от R1 моделей
                content = re.sub(r'<think>.*?</think>', '', row['content'], flags=re.DOTALL).strip()
                messages.append({"role": role, "content": content})

            # Текущее сообщение
            user_content = []
            text_part = current_message
            
            # Если модель текстовая, но пришла картинка
            if image_data and not supports_vision:
                text_part += " [Юзер прислал картинку, но ты (текстовая модель) её не видишь. Отшутись про это.]"
            
            user_content.append({"type": "text", "text": text_part})

            # Если модель видит картинки (на будущее)
            if image_data and supports_vision and img_b64:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })

            messages.append({"role": "user", "content": user_content})

            # Запрос к API
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
                text = response.choices[0].message.content
                # Чистим "мысли" для моделей типа R1/Chimera, чтобы они не попадали в чат
                text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
                
                logging.info(f"✅ Успешный ответ от {model_name}")
                return text

        except Exception as e:
            error_str = str(e)
            logging.warning(f"⚠️ {model_name} пропущена: {error_str[:60]}...")
            
            # Если первая модель (Chimera) жалуется на Data Policy
            if "data policy" in error_str.lower():
                logging.error("❌ ДЛЯ CHIMERA НУЖНО ВКЛЮЧИТЬ DATA TRAINING В НАСТРОЙКАХ OPENROUTER!")
            
            # Если лимит бесплатных запросов исчерпан
            if "free-models-per-day" in error_str:
                return "Лимит бесплатных сообщений на сегодня исчерпан. Я спать."
            
            continue

    logging.error("❌ Все модели недоступны")
    return None
