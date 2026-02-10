import logging
import base64
import io
import re
import random
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

Python
import logging
import base64
import io
import re
import random  # <--- ВОТ ЭТОГО ИМПОРТА НЕ ХВАТАЛО
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY
from services.shikimori import search_anime_info

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

MODELS = [
    {"name": "google/gemini-2.0-flash-001", "vision": False}, 
    {"name": "qwen/qwen-2.5-72b-instruct:free", "vision": False},
    {"name": "google/gemma-2-9b-it:free", "vision": False},
    {"name": "openrouter/free", "vision": False},
]

def clean_response(text):
    """Очищает ответ от мыслей модели (<think>) и приводит к строке."""
    if text is None: return ""
    if not isinstance(text, str): text = str(text)
    if not text: return ""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

def is_summary_query(text):
    """Проверка: просит ли юзер краткий пересказ?"""
    if not text: return False
    triggers = [
        "что тут происходит", "о чем речь", "кратко перескажи", 
        "что обсуждали", "саммари", "summary", "сводка", "итоги",
        "дай контекст", "что я пропустил"
    ]
    return any(t in text.lower() for t in triggers)

def is_event_query(text):
    """Проверка: просит ли юзер анонсы?"""
    if not text: return False
    text_lower = text.lower()
    triggers = [
        "куда сходить", "что делаем", "какие планы", "анонс", "встреча", 
        "где собираемся", "когда", "во сколько", "что будет",
        "фильм", "аниме", "кино", "ивент", "сегодня", "завтра", "выходные",
        "настолк", "игра", "мафия", "английск", "english", "клуб", "лекция", 
        "презентаци", "powerpoint", "pp", "поиграть", "сбор", "тусовка"
    ]
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

def determine_mood(text):
    """Определяет настроение: GENKI (веселое) или DOOMER (грустное)."""
    text = text.lower()
    doom_triggers = ["вода", "свет", "gwp", "отключ", "дорого", "ныть", "устал", "плохо", "дождь", "срач", "скучно"]
    genki_triggers = ["привет", "спасибо", "круто", "класс", "аниме", "пати", "весело", "любл", "ура", "игра"]
    
    if any(t in text for t in doom_triggers): return "DOOMER"
    elif any(t in text for t in genki_triggers): return "GENKI"
    
    # 70% веселья, 30% грусти
    return "GENKI" if random.random() < 0.7 else "DOOMER"

async def generate_response(db, chat_id, current_message, bot, image_data=None):
    # По умолчанию берем мало контекста
    history_rows = await db.get_context(chat_id, limit=6)
    
    found_events_text = ""
    shikimori_info = ""
    
    # Определяем типы запросов
    need_search = is_event_query(current_message)
    need_summary = is_summary_query(current_message)
    
    current_mood = determine_mood(current_message)
    logging.info(f"🎭 Mood: {current_mood} | Search: {need_search} | Summary: {need_summary}")
    
    # === ЛОГИКА СВОДКИ (SUMMARY) ===
    if need_summary:
        logging.info("📜 Запрос саммари. Скачиваем 50 сообщений...")
        # Перезаписываем историю на длинную
        history_rows = await db.get_chat_history_for_summary(chat_id, limit=50)

    # === ЛОГИКА ИВЕНТОВ ===
    elif need_search:
        raw_events = await db.get_potential_announcements(chat_id, days=60, limit=8)
        if raw_events:
            events_list = []
            full_text_batch = ""
            clean_chat_id = str(chat_id).replace("-100", "")
            
            for ev in raw_events:
                content = str(ev.get('content', ''))
                date = ev.get('timestamp').strftime('%d.%m')
                user = ev['user_name']
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
            
            if re.search(r"(аниме|anime|тайтл|сери|киберслав|смотреть|watch)", full_text_batch, re.IGNORECASE):
                detected_title = await extract_anime_title(full_text_batch)
                if detected_title:
                    anime_data = await search_anime_info(detected_title)
                    if anime_data:
                         shikimori_info = f"\n🎥 Справка Shikimori:\nНазвание: {anime_data['title']} ({anime_data['score']}⭐)\nЭпизоды: {anime_data['episodes']}\nСсылка: {anime_data['url']}"

    # === ОБЩИЙ ЛОР ===
    LORE = """
ЗНАНИЕ ЛОКАЛЬНЫХ МЕМОВ (Использовать ситуативно):
1. Про тесноту: "Слишком много мужчин на кроватный метр."
2. Если кто-то умничает: "Анимешникам слова не давали."
3. Про споры: "Уроки мастерства от Алмаза по разведению срачей."
4. Про бар/питье: "Аниме ячейка — повод для алкоголизма."
5. Если ностальгия: "Ячейка уже не та..."
6. Про воду (GWP): "В Тбилиси два агрегатных состояния воды: либо её нет, либо она течет с потолка."
7. Про женский чат: "Тайны женского чата неприкосновенны."
"""

    if current_mood == "GENKI":
        PERSONA_CORE = """
Ты — Ячейка-тян, веселый маскот! ✨
Ты любишь движ и своих подписчиков.
Ты используешь смайлики и шутишь по-доброму.
"""
    else:
        PERSONA_CORE = """
Ты — Ячейка-тян, ироничная экспатка в Тбилиси.
Ты устала от суеты. Говоришь сухо, саркастично, по фактам.
Твой вайб — интеллектуальный снобизм.
"""

    FULL_SYSTEM_PROMPT = f"{PERSONA_CORE}\n\n{LORE}"

    # === ВЫБОР ИНСТРУКЦИИ ===
    if need_summary:
        task_instruction = """
РЕЖИМ: ГЕНЕРАЦИЯ СВОДКИ (SUMMARY).
Тебе даны последние 50 сообщений из чата.
Твоя задача:
1. Кратко пересказать, о чем говорили люди.
2. Выделить главные темы.
3. Упомянуть самых активных участников по именам.
4. Если был просто флуд — так и скажи.
"""
    elif need_search:
        if found_events_text:
            task_instruction = """
РЕЖИМ: ГИД ПО ИВЕНТАМ.
1. Расскажи, куда сходить.
2. ОБЯЗАТЕЛЬНО дай ссылку на пост.
"""
        else:
            task_instruction = "В базе пусто. Если веселая — предложи сама что-то, если грустная — отправь в закреп."
    else:
        task_instruction = "Светская беседа. Реагируй на контекст."

    # Собираем сообщения
    messages = [{"role": "system", "content": f"{FULL_SYSTEM_PROMPT}\n{found_events_text}\n{shikimori_info}\n{task_instruction}"}]

    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        content_clean = clean_response(row.get('content'))
        user_name = row.get('user_name', 'Anon')
        
        # Для саммари важно знать, КТО пишет
        if need_summary and role == "user":
            content_clean = f"{user_name}: {content_clean}"
            
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
            tokens = 1200 if (need_search or need_summary) else 400
            temp = 0.6 if current_mood == "GENKI" else 0.3
            
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=temp,
                max_tokens=tokens,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )
            if response.choices:
                return clean_response(response.choices[0].message.content)
        except Exception: continue

    return None
