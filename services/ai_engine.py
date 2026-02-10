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
    if not text: return False
    text_lower = text.lower()
    
    # 1. Явные вопросы "Где/Когда"
    question_triggers = [
        "куда сходить", "что делаем", "какие планы", "анонс", "встреча", 
        "где собираемся", "когда", "во сколько", "что будет"
    ]
    
    # 2. Ключевые слова мероприятий
    event_keywords = [
        "фильм", "аниме", "кино", "ивент", "сегодня", "завтра", "выходные",
        "настолк", "игра", "мафия", "английск", "english", "клуб", "лекция", 
        "презентаци", "powerpoint", "pp", "поиграть", "сбор", "тусовка"
    ]
    
    # Объединяем списки (ВОТ ЭТА СТРОКА БЫЛА ПРОПУЩЕНА)
    triggers = question_triggers + event_keywords
    
    return any(t in text_lower for t in triggers)

async def extract_anime_title(text):
    try:
        messages = [
            {"role": "system", "content": "Твоя задача: найти название аниме или фильма. Верни ТОЛЬКО название. Если нет, верни 'NO'."},
            {"role": "user", "content": f"Текст:\n{text[:800]}"}
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
    # 1. Быстрый контекст диалога (последние 6 сообщений)
    history_rows = await db.get_context(chat_id, limit=6)
    
    found_events_text = ""
    shikimori_info = ""
    
    # Проверка: это вопрос про ивент?
    need_search = is_event_query(current_message)
    
    # 2. ЕСЛИ ЭТО ВОПРОС ПРО ИВЕНТ -> ЛЕЗЕМ В БАЗУ ГЛУБОКО
    if need_search:
        # Берем 8 последних постов из ветки анонсов (RAW, без фильтров)
        raw_events = await db.get_potential_announcements(chat_id, days=45, limit=8)
        
        if raw_events:
            events_list = []
            full_text_batch = ""
            for ev in raw_events:
                content = ev['content']
                date = ev.get('timestamp').strftime('%d.%m')
                user = ev['user_name']
                events_list.append(f"--- [Пост от {user} | {date}] ---\n{content}\n")
                full_text_batch += content + "\n"
            
            found_events_text = "📍 ПОСЛЕДНИЕ СООБЩЕНИЯ ИЗ ВЕТКИ АНОНСОВ:\n" + "\n".join(events_list)

            # 3. Shikimori (Ищем инфу, только если есть намек на аниме)
            if re.search(r"(аниме|anime|тайтл|сери|киберслав|смотреть|watch)", full_text_batch, re.IGNORECASE):
                detected_title = await extract_anime_title(full_text_batch)
                if detected_title:
                    anime_data = await search_anime_info(detected_title)
                    if anime_data:
                         shikimori_info = f"\n🎥 Справка Shikimori:\nНазвание: {anime_data['title']} ({anime_data['score']}⭐)\nЭпизоды: {anime_data['episodes']}\nСсылка: {anime_data['url']}"

    # === СИСТЕМНЫЙ ПРОМПТ ===
    PERSONA = "Ты — Ячейка-тян, бот-помощник."

    if need_search:
        if found_events_text:
            system_instruction = f"""{PERSONA}
РЕЖИМ: ГИД ПО МЕРОПРИЯТИЯМ.

КОНТЕКСТ (Посты из канала анонсов):
{found_events_text}
{shikimori_info}

ИНСТРУКЦИЯ:
1. Проанализируй тексты и расскажи, какие планируются мероприятия (PowerPoint, аниме, игры и т.д.).
2. Если пользователь спрашивает конкретно (например, "Когда PowerPoint?"), найди ответ в тексте.
3. Если данных Shikimori нет — ничего страшного, просто перескажи анонс.
"""
        else:
            system_instruction = f"{PERSONA}\nЯ проверила ветку анонсов, но там пусто. Посоветуй проверить закреп или спросить админа."
    else:
        system_instruction = f"{PERSONA}\nВедем светскую беседу. Отвечай кратко, с долей иронии."

    messages = [{"role": "system", "content": system_instruction}]

    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        messages.append({"role": role, "content": clean_response(row['content'])})

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
        except Exception: pass

    messages.append({"role": "user", "content": user_content})

    for model_cfg in MODELS:
        try:
            tokens = 1000 if need_search else 300
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.3,
                max_tokens=tokens,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )
            if response.choices:
                return clean_response(response.choices[0].message.content)
        except Exception: continue

    return None
