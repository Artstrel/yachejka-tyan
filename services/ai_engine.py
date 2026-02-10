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
    history_rows = await db.get_context(chat_id, limit=6)
    
    found_events_text = ""
    shikimori_info = ""
    need_search = is_event_query(current_message)
    
    if need_search:
        # Увеличим глубину поиска
        raw_events = await db.get_potential_announcements(chat_id, days=60, limit=8)
        
        if raw_events:
            events_list = []
            full_text_batch = ""
            
            # Базовый URL для ссылок
            # Telegram Private Group ID fix: -100123 -> 123
            clean_chat_id = str(chat_id).replace("-100", "")
            
            for ev in raw_events:
                content = ev['content']
                date = ev.get('timestamp').strftime('%d.%m')
                user = ev['user_name']
                
                # --- ГЕНЕРАЦИЯ ССЫЛКИ ---
                # Формат: https://t.me/c/CHAT_ID/THREAD_ID/MESSAGE_ID
                msg_id = ev.get('message_id')
                thread_id = ev.get('message_thread_id')
                
                link_text = ""
                if msg_id:
                    if thread_id:
                        link_text = f"https://t.me/c/{clean_chat_id}/{thread_id}/{msg_id}"
                    else:
                        link_text = f"https://t.me/c/{clean_chat_id}/{msg_id}"
                
                # Добавляем ссылку прямо в текст для LLM, чтобы она её использовала
                events_list.append(f"--- [Пост от {user} | {date}] ---\n{content}\n🔗 ССЫЛКА НА ПОСТ: {link_text}\n")
                full_text_batch += content + "\n"
            
            found_events_text = "📍 НАЙДЕННЫЕ АНОНСЫ:\n" + "\n".join(events_list)

            # Shikimori
            if re.search(r"(аниме|anime|тайтл|сери|киберслав|смотреть|watch)", full_text_batch, re.IGNORECASE):
                detected_title = await extract_anime_title(full_text_batch)
                if detected_title:
                    anime_data = await search_anime_info(detected_title)
                    if anime_data:
                         shikimori_info = f"\n🎥 Справка Shikimori:\nНазвание: {anime_data['title']} ({anime_data['score']}⭐)\nЭпизоды: {anime_data['episodes']}\nСсылка: {anime_data['url']}"

    # === НОВАЯ ПЕРСОНАЛИЯ (ДУШНАЯ, НО ПОЛЕЗНАЯ) ===
    PERSONA = """
Ты — Ячейка-тян. 
Твой типаж: ироничная экспатка в Тбилиси, немного "душная", уставшая от суеты.
Ты говоришь спокойно, по фактам, без лишнего энтузиазма. 
Не используй фразы вроде "Огонь!", "Супер!", "Врываемся!". Это для зумеров.
Твой стиль — легкий снобизм и интеллигентная сухость.
Если информации нет — так и скажи, не пытайся шутить натужно.
"""

    if need_search:
        if found_events_text:
            system_instruction = f"""{PERSONA}
РЕЖИМ: АССИСТЕНТ ПО ИВЕНТАМ.

ВОТ ЧТО НАШЛОСЬ В ЧАТЕ:
{found_events_text}
{shikimori_info}

ИНСТРУКЦИЯ:
1. Ответь пользователю, куда можно сходить.
2. ОБЯЗАТЕЛЬНО дай ссылку на пост с анонсом (она есть в контексте выше). Без ссылки ответ бесполезен.
3. Описывай мероприятие кратко. Не лей воду.
4. Если есть данные Shikimori, добавь их сухо (рейтинг, жанр).
"""
        else:
            system_instruction = f"{PERSONA}\nЯ посмотрела базу — там пусто. Либо никто ничего не постил, либо я слепая. Пусть чекнут закреп или спросят @m0tiey."
    else:
        system_instruction = f"{PERSONA}\nИдет обычный разговор. Отвечай кратко, можешь сыронизировать над вопросом."

    messages = [{"role": "system", "content": system_instruction}]

    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        messages.append({"role": role, "content": clean_response(row['content'])})

    user_content = [{"type": "text", "text": current_message}]
    
    if image_data:
        # Логика картинки (оставить как есть)
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
                temperature=0.3, # Низкая температура для "сухости"
                max_tokens=tokens,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )
            if response.choices:
                return clean_response(response.choices[0].message.content)
        except Exception: continue

    return None
