import logging
import base64
import io
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# === СПИСОК БЕСПЛАТНЫХ МОДЕЛЕЙ (FALLBACK) ===
# Бот будет пробовать их по очереди сверху вниз.
MODELS = [
    # 1. Google Gemini 2.0 Flash (Experimental)
    # Быстрая, видит картинки, обычно самый высокий лимит для free.
    {"name": "google/gemini-2.0-flash-exp:free", "vision": True},

    # 2. Llama 3.3 70B (Meta)
    # Очень умная, но часто бывает перегружена (429).
    {"name": "meta-llama/llama-3.3-70b-instruct:free", "vision": False},

    # 3. Qwen 2.5 VL 72B (Alibaba)
    # Видит картинки, понимает русский лучше всех.
    {"name": "qwen/qwen-2.5-vl-72b-instruct:free", "vision": True},

    # 4. Mistral Nemo 12B (Mistral AI)
    # Средний размер, очень стабильная и быстрая.
    {"name": "mistralai/mistral-nemo:free", "vision": False},

    # 5. Phi-3 Mini (Microsoft)
    # Маленькая модель. Если всё остальное лежит — эта обычно работает.
    {"name": "microsoft/phi-3-mini-128k-instruct:free", "vision": False},
    
    # 6. HRryge / Dolphin (Uncensored)
    # Запасной вариант, если нужна модель без цензуры.
    {"name": "cognitivecomputations/dolphin-mixtral-8x7b:free", "vision": False},
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

    # Подготовка картинки (один раз)
    img_b64 = None
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        except Exception as e:
            logging.error(f"⚠️ Ошибка обработки картинки: {e}")

    # Перебор моделей
    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        supports_vision = model_cfg["vision"]

        try:
            messages = []
            
            # Система
            sys_msg = PERSONA
            if median_len <= 40:
                sys_msg += "\nИНСТРУКЦИЯ: Пиши максимально лаконично, одной фразой."
            messages.append({"role": "system", "content": sys_msg})

            # История
            for row in history_rows:
                role = "assistant" if row['role'] == "model" else "user"
                # Очистка от <think>, если вдруг попалось в истории
                import re
                content = re.sub(r'<think>.*?</think>', '', row['content'], flags=re.DOTALL).strip()
                messages.append({"role": role, "content": content})

            # Текущее сообщение
            user_content = []
            
            text_part = current_message
            # Если модель слепая, но есть картинка — пишем текстом
            if image_data and not supports_vision:
                text_part += " [Пользователь прислал фото, но ты текстовая модель. Придумай едкий комментарий об этом.]"
            
            user_content.append({"type": "text", "text": text_part})

            # Если модель зрячая — добавляем картинку
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
                temperature=0.7,
                max_tokens=600,
                extra_headers={
                    "HTTP-Referer": "https://telegram.org",
                    "X-Title": "Yachejka Bot"
                }
            )

            if response.choices and response.choices[0].message.content:
                logging.info(f"✅ Ответ получен от: {model_name}")
                return response.choices[0].message.content

        except Exception as e:
            error_str = str(e)
            logging.warning(f"⚠️ {model_name} недоступна: {error_str[:60]}...")
            
            # Если словили суточный лимит аккаунта — прерываем цикл сразу.
            # (Тут ничего не поделаешь кодом, только ждать сброса таймера OpenRouter)
            if "free-models-per-day" in error_str:
                logging.error("❌ СУТОЧНЫЙ ЛИМИТ OpenRouter ИСЧЕРПАН.")
                return None 

            continue

    logging.error("❌ Все бесплатные модели сейчас лежат или перегружены.")
    return None
