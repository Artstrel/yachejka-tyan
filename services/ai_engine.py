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
    
    # Берем больше анонсов (5), чтобы точно найти нужное
    raw_events = await db.get_potential_announcements(chat_id, days=14, limit=5)

    found_events_text = ""
    has_relevant_info = False
    
    if raw_events:
        events_list = []
        for ev in raw_events:
            content = ev['content']
            date_str = ev.get('timestamp').strftime('%d.%m')
            user_name = ev['user_name']
            events_list.append(f"--- POST BY {user_name} ({date_str}) ---\n{content}\n---------------------------")
        
        found_events_text = "⚠️ ACTUAL ANNOUNCEMENTS FROM CHAT:\n" + "\n".join(events_list)
        has_relevant_info = True

    # === СИСТЕМНЫЙ ПРОМПТ С ПРИМЕРАМИ (FEW-SHOT) ===
    
    if has_relevant_info:
        SYSTEM_PROMPT = f"""
Ты — Ячейка-тян. Твоя задача — извлечь детали мероприятий из текста и ответить пользователю.

ВОТ ПРИМЕРЫ ТОГО, КАК ВЫГЛЯДЯТ АНОНСЫ В ЭТОМ ЧАТЕ (ИЗУЧИ ИХ СТРУКТУРУ):

Пример 1 (КиберСлав):
"Суббота - 07.02 - 19:00 (everyweek) ... 🪧Место - Bar d22"
-> Тут дата в начале, а место в конце с эмодзи 🪧.

Пример 2 (Мафия/Clocktower):
"🎩Blood on the Clocktower🕐 ... 📅 6 февраля ... 📍 Бар Red&Wine"
-> Тут вся инфа списком внизу с эмодзи 📅, 🕓, 📍.

Пример 3 (Проектор/PowerPoint):
"Открытый проектор👉 18 января 19:00 |D22 Bar"
-> Тут дата и место в одну строку через разделитель "|".

Пример 4 (Книжный клуб):
"📕 Следующая встреча... Место: Coffee Lars"
-> Тут место указано словом "Место:".

ТЕКСТ НАЙДЕННЫХ СООБЩЕНИЙ:
{found_events_text}

ИНСТРУКЦИЯ:
1. Найди в тексте выше информацию о мероприятии, про которое спросил пользователь.
2. Ответь в формате:
   ✨ [Название]
   📅 [Дата и Время]
   📍 [Место] (Если D22 Bar - уточни адрес: 4 Amaghleba St)
   💰 [Вход/Цена]
   📝 [Короткое описание в 1 предложение]
   
3. Если пользователь просто спросил "Куда сходить?" — перечисли все найденные актуальные анонсы кратко.
4. Стиль: Полезный помощник. Сарказм выключен.
"""
    else:
        # РЕЖИМ: НЕТ ДАННЫХ
        SYSTEM_PROMPT = """
Ты — Ячейка-тян, циничная экспатка.
Контекст: Я просканировала чат, но не нашла свежих анонсов.

Если спрашивают "Куда сходить?":
- Скажи: "В базе анонсов пусто. Видимо, все уехали или спились."
- Пошути про закрытые Kawaii Sushi.

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
                temperature=0.4, # Низкая температура для точности фактов
                max_tokens=1000,
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
