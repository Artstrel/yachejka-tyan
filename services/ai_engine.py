import logging
import base64
import io
import re
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY
from services.shikimori import search_anime_info # <-- Импортируем наш сервис

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

def is_event_query(text):
    """Определяет, спрашивает ли юзер про активность."""
    text_lower = text.lower()
    
    # 1. Сначала проверяем явные вопросы "Куда/Когда"
    question_triggers = [
        "куда сходить", "что делаем", "какие планы", "анонс", "встреча", 
        "где собираемся", "когда", "во сколько", "что будет"
    ]
    
    # 2. Потом проверяем ключевые слова ивентов
    event_keywords = [
        "фильм", "аниме", "кино", "ивент", "сегодня", "завтра", "выходные",
        "настолк", "игра", "мафия", "английск", "english", "клуб", "лекция", 
        "презентаци", "powerpoint", "pp", "поиграть", "сбор"
    ]
    return any(t in text_lower for t in triggers)

async def extract_anime_title(text):
    try:
        messages = [
            {"role": "system", "content": "Твоя задача: найти название аниме/фильма. Верни ТОЛЬКО название. Если нет, верни 'NO'."},
            {"role": "user", "content": f"Текст:\n{text[:1000]}"}
        ]
        response = await client.chat.completions.create(
            model="google/gemma-2-9b-it:free",
            messages=messages,
            temperature=0.1,
            max_tokens=30
        )
        title = response.choices[0].message.content.strip()
        title = re.sub(r"['\"«»]", "", title)
        return title if title != "NO" and len(title) > 2 else None
    except Exception: return None

async def generate_response(db, chat_id, current_message, bot, image_data=None):
    # 1. Быстрый контекст диалога (последние 8 сообщений)
    history_rows = await db.get_context(chat_id, limit=8)
    
    found_events_text = ""
    shikimori_info = ""
    need_search = is_event_query(current_message)
    
    # 2. ЕСЛИ ВОПРОС ПРО ИВЕНТЫ -> Лезем в ветку анонсов
    if need_search:
        # Берем 5 последних сообщений из ветки анонсов (очень быстро)
        raw_events = await db.get_potential_announcements(chat_id, days=30, limit=5)
        
        if raw_events:
            events_list = []
            full_text_batch = ""
            for ev in raw_events:
                content = ev['content']
                date = ev.get('timestamp').strftime('%d.%m')
                user = ev['user_name']
                events_list.append(f"--- [Пост от {user} | {date}] ---\n{content}\n")
                full_text_batch += content + "\n"
            
            found_events_text = "📍 ИНФОРМАЦИЯ ИЗ ВЕТКИ АНОНСОВ:\n" + "\n".join(events_list)

            # Shikimori проверка
            if re.search(r"(аниме|anime|тайтл|сери|киберслав)", full_text_batch, re.IGNORECASE):
                detected_title = await extract_anime_title(full_text_batch)
                if detected_title:
                    anime_data = await search_anime_info(detected_title)
                    if anime_data:
                         shikimori_info = f"\n🎥 Shikimori Info:\nНазвание: {anime_data['title']} ({anime_data['score']}⭐)\nЭпизоды: {anime_data['episodes']}\nСсылка: {anime_data['url']}"

    # === ПРОМПТ ===
    PERSONA = "Ты — Ячейка-тян, бот-помощник."

    if need_search:
        if found_events_text:
            system_instruction = f"""{PERSONA}
РЕЖИМ: АНАЛИЗ ИВЕНТОВ.

{found_events_text}
{shikimori_info}

ИНСТРУКЦИЯ:
1. Используй посты из ветки анонсов, чтобы ответить, куда сходить.
2. Обращай внимание на даты.
3. Если есть инфа с Shikimori, добавь её.
"""
        else:
            system_instruction = f"{PERSONA}\nЯ посмотрела ветку анонсов, но там пусто или нет свежего."
    else:
        system_instruction = f"{PERSONA}\nОбычный диалог. Отвечай кратко и иронично."

    messages = [{"role": "system", "content": system_instruction}]

    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        messages.append({"role": role, "content": clean_response(row['content'])})

    user_content = [{"type": "text", "text": current_message}]
    if image_data: pass 

    messages.append({"role": "user", "content": user_content})

    for model_cfg in MODELS:
        try:
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.3,
                max_tokens=800 if need_search else 250, # Экономим
            )
            if response.choices:
                return clean_response(response.choices[0].message.content)
        except Exception: continue

    return None
