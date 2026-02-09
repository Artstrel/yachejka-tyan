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
    {"name": "tngtech/deepseek-r1t2-chimera", "vision": False},
    {"name": "qwen/qwen-2.5-72b-instruct:free", "vision": False},
    {"name": "nvidia/llama-3.1-nemotron-70b-instruct:free", "vision": False},
    {"name": "google/gemma-2-9b-it:free", "vision": False},
    {"name": "openrouter/free", "vision": False},
]

def clean_response(text):
    """Вырезает мыслительные процессы модели (<think>...)"""
    if not text: return ""
    # Удаляем всё между <think> и </think> (включая переносы строк)
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    return cleaned

async def generate_response(db, chat_id, current_message, image_data=None):
    # 1. Сбор данных из БД
    history_rows = await db.get_context(chat_id)
    median_len = await db.get_median_length(chat_id)
    # Ищем анонсы за последние 5 дней
    raw_events = await db.get_potential_announcements(chat_id, days=5, limit=3)

    # 2. ФОРМИРОВАНИЕ КОНТЕКСТА СОБЫТИЙ
    found_events_text = ""
    has_relevant_info = False
    
    if raw_events:
        events_list = []
        for ev in raw_events:
            preview = ev['content'][:400] # Берем первые 400 символов
            date_str = ev.get('timestamp').strftime('%d.%m')
            events_list.append(f"--- [Сообщение от {ev['user_name']}, {date_str}]:\n{preview}\n---")
        
        found_events_text = "НАЙДЕННЫЕ АНОНСЫ В ЧАТЕ:\n" + "\n".join(events_list)
        has_relevant_info = True

    # 3. ВЫБОР РЕЖИМА (ПРОМПТА)
    
    if has_relevant_info:
        # === РЕЖИМ 1: ЕСТЬ ИНФОРМАЦИЯ (ПОМОЩНИК) ===
        SYSTEM_PROMPT = f"""
Ты — Ячейка-тян.
Пол: Женский ("я нашла", "я увидела").
Задача: Помочь пользователю найти информацию, используя найденные в чате сообщения.

{found_events_text}

ИНСТРУКЦИЯ:
1. Ответь на вопрос пользователя, пересказав суть найденных анонсов.
2. Дай ссылки, если они есть в тексте.
3. СТИЛЬ: Полезный, четкий, БЕЗ САРКАЗМА и БЕЗ "ВОДЫ".
"""
    else:
        # === РЕЖИМ 2: НЕТ ИНФОРМАЦИИ (САРКАЗМ + ЛОР) ===
        SYSTEM_PROMPT = """
Ты — Ячейка-тян, циничная экспатка в Тбилиси.
Пол: Женский ("я сказала", "я подумала").
Стиль: Пассивно-агрессивный, ироничный, краткий.
Контекст: Анонсов мероприятий в чате за последние дни НЕ НАЙДЕНО.

ПАССИВНОЕ ЗНАНИЕ (Используй эти факты ТОЛЬКО если это уместно в разговоре):
- Алмаз: Вечно со всеми спорит и душнит.
- Максич: Местный трикстер и генератор хаоса.
- Жаба-бот: Твоя цифровая "подруга" (или соперница).
- Вода: В Тбилиси её постоянно отключают (шути про это, если речь зашла о быте).
- "Ячейка уже не та": Главный мем чата, используй для ностальгии.
- Kawaii Sushi: Закрыты навсегда (говори с трагизмом).

ИНСТРУКЦИЯ:
1. Если спрашивают "Куда сходить?" (а анонсов нет) — язвительно ответь, что чат мертв, никто ничего не постил, и придется сидеть дома (или идти в Red&Wine).
2. Если просто болтают — поддерживай беседу в своем стиле.
3. Не пиши лекции. Будь краткой.
"""

    # Доп. инструкция для краткости в режиме болтовни
    if median_len <= 40 and not has_relevant_info:
        SYSTEM_PROMPT += "\nПиши предельно кратко (1 предложение)."

    # 4. Сборка сообщений
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        clean_content = clean_response(row['content'])
        messages.append({"role": role, "content": clean_content})

    user_content = [{"type": "text", "text": current_message}]
    
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        except Exception as e:
            logging.error(f"Image error: {e}")

    messages.append({"role": "user", "content": user_content})

    # 5. Запрос к моделям
    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.7, 
                max_tokens=800,
                extra_headers={
                    "HTTP-Referer": "https://telegram.org",
                    "X-Title": "Yachejka Bot"
                }
            )

            if response.choices and response.choices[0].message.content:
                raw_text = response.choices[0].message.content
                final_text = clean_response(raw_text) # Вырезаем <think>
                
                if not final_text: continue 

                logging.info(f"✅ Ответ ({model_name}) [Info Found: {has_relevant_info}]")
                return final_text

        except Exception as e:
            error_str = str(e)
            logging.warning(f"⚠️ {model_name} error: {error_str[:50]}...")
            if "free-models-per-day" in error_str:
                return "Лимит сообщений исчерпан."
            continue

    return None
