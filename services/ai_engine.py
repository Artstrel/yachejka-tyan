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

MODELS = [
    {"name": "tngtech/deepseek-r1t2-chimera", "vision": False},
    {"name": "qwen/qwen-2.5-72b-instruct:free", "vision": False},
    {"name": "nvidia/llama-3.1-nemotron-70b-instruct:free", "vision": False},
    {"name": "google/gemma-2-9b-it:free", "vision": False},
    {"name": "openrouter/free", "vision": False},
]

def clean_response(text):
    if not text: return ""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

async def generate_response(db, chat_id, current_message, image_data=None):
    history_rows = await db.get_context(chat_id)
    median_len = await db.get_median_length(chat_id)
    
    # Ищем анонсы (теперь это умный поиск по ветке)
    raw_events = await db.get_potential_announcements(chat_id, days=10, limit=2)

    found_events_text = ""
    has_relevant_info = False
    
    if raw_events:
        events_list = []
        for ev in raw_events:
            # Даем боту полный текст анонса, чтобы он нашел детали
            # Добавляем маркер [ФОТО], если сообщение было с картинкой (обычно caption)
            content = ev['content']
            date_str = ev.get('timestamp').strftime('%d.%m')
            events_list.append(f"=== АНОНС ({date_str}) ===\n{content}\n==================")
        
        found_events_text = "ПОСЛЕДНИЕ СООБЩЕНИЯ ИЗ ВЕТКИ 'НОВОСТИ И АНОНСЫ':\n" + "\n".join(events_list)
        has_relevant_info = True

    # === ЛОГИКА ВЫБОРА ПРОМПТА ===
    
    if has_relevant_info:
        # РЕЖИМ: АНАЛИЗАТОР АФИШ
        SYSTEM_PROMPT = f"""
Ты — Ячейка-тян. Твоя задача — быть полезным гидом по событиям.

{found_events_text}

ИНСТРУКЦИЯ:
Ты видишь текст реальных анонсов выше. Пользователь спрашивает о мероприятиях.
Твоя задача — проанализировать текст анонсов и извлечь:
1. ЧТО (Название, формат).
2. КОГДА (Дата и Время).
3. ГДЕ (Локация, адрес).
4. ЦЕНА/ВХОД (если указано).

Ответь пользователю четко: "Я нашла анонс: [Название] будет [Дата/Время] в [Место]. Детали: ..."
Если в анонсе есть ссылка — обязательно дай её.
Стиль: Спокойный, полезный. Без лишнего сарказма, когда речь идет о датах и цифрах.
"""
    else:
        # РЕЖИМ: НЕТ ДАННЫХ
        SYSTEM_PROMPT = """
Ты — Ячейка-тян, циничная экспатка.
Контекст: В ветке анонсов ПУСТО (или я не вижу свежих постов за 10 дней).

Если спрашивают "Куда сходить?":
- Скажи честно: "В ветке анонсов тишина. Видимо, город вымер."
- Пошути, что придется идти пить вино на лавочке.
- Напомни про закрытые Kawaii Sushi.

Стиль: Пассивно-агрессивный, краткий.
"""

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

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.5, # Ставим 0.5, чтобы она точно брала факты, а не выдумывала даты
                max_tokens=900,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )

            if response.choices and response.choices[0].message.content:
                final_text = clean_response(response.choices[0].message.content)
                if not final_text: continue
                return final_text

        except Exception as e:
            if "free-models-per-day" in str(e): return "Лимит исчерпан."
            continue

    return None
