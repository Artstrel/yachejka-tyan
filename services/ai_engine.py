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

# --- ИСПРАВЛЕННАЯ ФУНКЦИЯ ---
def clean_response(text):
    """Очищает ответ от мыслей модели (<think>) и приводит к строке."""
    if text is None: 
        return ""
    # Если пришло число или объект - превращаем в строку
    if not isinstance(text, str):
        text = str(text)
    
    if not text: 
        return ""
        
    # Удаляем теги <think> и всё что внутри
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    return text

def is_event_query(text):
    if not text: return False
    text_lower = text.lower()
    
    question_triggers = [
        "куда сходить", "что делаем", "какие планы", "анонс", "встреча", 
        "где собираемся", "когда", "во сколько", "что будет"
    ]
    event_keywords = [
        "фильм", "аниме", "кино", "ивент", "сегодня", "завтра", "выходные",
        "настолк", "игра", "мафия", "английск", "english", "клуб", "лекция", 
        "презентаци", "powerpoint", "pp", "поиграть", "сбор", "тусовка"
    ]
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
    # Берем историю
    history_rows = await db.get_context(chat_id, limit=6)
    
    found_events_text = ""
    shikimori_info = ""
    need_search = is_event_query(current_message)
    
    if need_search:
        # Логируем для проверки
        logging.info(f"🔎 Ищу анонсы...")
        raw_events = await db.get_potential_announcements(chat_id, days=60, limit=8)
        
        if raw_events:
            events_list = []
            full_text_batch = ""
            
            # Чистим ID чата для ссылки (убираем -100)
            clean_chat_id = str(chat_id).replace("-100", "")
            
            for ev in raw_events:
                # Защита от None в content
                content = str(ev.get('content', ''))
                date = ev.get('timestamp').strftime('%d.%m')
                user = ev['user_name']
                
                # Генерация ссылки
                msg_id = ev.get('message_id')
                thread_id = ev.get('message_thread_id')
                
                link_text = ""
                if msg_id:
                    if thread_id:
                        link_text = f"https://t.me/c/{clean_chat_id}/{thread_id}/{msg_id}"
                    else:
                        link_text = f"https://t.me/c/{clean_chat_id}/{msg_id}"
                
                events_list.append(f"--- [Пост от {user} | {date}] ---\n{content}\n🔗 ССЫЛКА: {link_text}\n")
                full_text_batch += content + "\n"
            
            found_events_text = "📍 НАЙДЕННЫЕ АНОНСЫ:\n" + "\n".join(events_list)

            # Shikimori
            if re.search(r"(аниме|anime|тайтл|сери|киберслав|смотреть|watch)", full_text_batch, re.IGNORECASE):
                detected_title = await extract_anime_title(full_text_batch)
                if detected_title:
                    anime_data = await search_anime_info(detected_title)
                    if anime_data:
                         shikimori_info = f"\n🎥 Справка Shikimori:\nНазвание: {anime_data['title']} ({anime_data['score']}⭐)\nЭпизоды: {anime_data['episodes']}\nСсылка: {anime_data['url']}"

    # === ПЕРСОНАЛИЯ ===
    PERSONA = """
Ты — Ячейка-тян. 
Твой типаж: ироничная экспатка в Тбилиси, интеллигентная, немного уставшая.
Ты говоришь спокойно, по фактам. Не используй кринжовый молодежный сленг.
"""

    if need_search:
        if found_events_text:
            system_instruction = f"""{PERSONA}
РЕЖИМ: ГИД ПО ИВЕНТАМ.

ВОТ АНОНСЫ ИЗ ЧАТА:
{found_events_text}
{shikimori_info}

ИНСТРУКЦИЯ:
1. Кратко расскажи, что планируется.
2. ОБЯЗАТЕЛЬНО дай ссылку на пост (бери из контекста).
3. Если инфы с Shikimori нет - не выдумывай.
"""
        else:
            system_instruction = f"{PERSONA}\nВ базе пусто. Скажи проверить закреп или спросить админа."
    else:
        system_instruction = f"{PERSONA}\nСветская беседа. Будь краткой."

    messages = [{"role": "system", "content": system_instruction}]

    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        # Вот здесь раньше падало, теперь будет работать:
        content_clean = clean_response(row.get('content'))
        if content_clean:
            messages.append({"role": role, "content": content_clean})

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
