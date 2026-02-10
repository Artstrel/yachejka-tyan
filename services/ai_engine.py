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

def clean_response(text):
    """Очищает ответ от мусора."""
    if text is None: return ""
    if not isinstance(text, str): text = str(text)
    if not text: return ""
    # Удаляем мысли <think>
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Удаляем повторы, если бот начал зацикливаться (простая защита)
    lines = text.split('\n')
    unique_lines = []
    seen = set()
    for line in lines:
        if line.strip() in seen: continue
        if len(line.strip()) > 5: seen.add(line.strip())
        unique_lines.append(line)
    return "\n".join(unique_lines).strip()

def is_summary_query(text):
    if not text: return False
    triggers = ["что тут происходит", "о чем речь", "кратко перескажи", "саммари", "summary", "сводка", "итоги"]
    return any(t in text.lower() for t in triggers)

def is_event_query(text):
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
            {"role": "system", "content": "Find the anime title in the text. Return ONLY the title. If none, return 'NO'."},
            {"role": "user", "content": f"Text:\n{text[:800]}"}
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
    text = text.lower()
    # Упрощенные триггеры
    doom_triggers = ["вода", "свет", "gwp", "отключ", "дорого", "ныть", "устал", "плохо", "грусть"]
    genki_triggers = ["привет", "спасибо", "круто", "класс", "аниме", "пати", "весело", "ура"]
    
    if any(t in text for t in doom_triggers): return "SARCASM" # Заменили DOOMER на SARCASM (безопаснее)
    elif any(t in text for t in genki_triggers): return "GENKI"
    return "GENKI" if random.random() < 0.7 else "SARCASM"

async def generate_response(db, chat_id, current_message, bot, image_data=None):
    history_rows = await db.get_context(chat_id, limit=6)
    
    found_events_text = ""
    shikimori_info = ""
    
    need_search = is_event_query(current_message)
    need_summary = is_summary_query(current_message)
    current_mood = determine_mood(current_message)
    
    # === СБОР ДАННЫХ ===
    if need_summary:
        history_rows = await db.get_chat_history_for_summary(chat_id, limit=50)

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
                # Генерация ссылки
                link_text = f"https://t.me/c/{clean_chat_id}/{msg_id}" if msg_id else ""
                
                events_list.append(f"--- [Пост от {user} | {date}] ---\n{content}\n🔗: {link_text}\n")
                full_text_batch += content + "\n"
            
            found_events_text = "📍 АНОНСЫ:\n" + "\n".join(events_list)
            
            if re.search(r"(аниме|anime|тайтл|сери|киберслав|смотреть)", full_text_batch, re.IGNORECASE):
                detected_title = await extract_anime_title(full_text_batch)
                if detected_title:
                    anime_data = await search_anime_info(detected_title)
                    if anime_data:
                         shikimori_info = f"\n🎥 Shikimori: {anime_data['title']} ({anime_data['score']}⭐) {anime_data['url']}"

    # === ЛОР (Смягченный) ===
    LORE = """
КОНТЕКСТ:
1. Теснота: "Слишком много мужчин на кроватный метр."
2. Нытье: "Поплачь еще."
3. Бар: "Аниме ячейка — повод для алкоголизма."
4. Вода: "В Тбилиси вода либо течет с потолка, либо её нет."
"""

    # === ПЕРСОНАЛИЯ (Стабилизированная) ===
    if current_mood == "GENKI":
        PERSONA_CORE = """
Ты — Ячейка-тян, веселый бот-помощник! ✨
Отвечай коротко, позитивно, используй смайлики.
Не пиши бред, не повторяйся.
"""
    else:
        # Убрали слова "устала", "душнила", чтобы бот не впадал в депрессию
        PERSONA_CORE = """
Ты — Ячейка-тян. Ты говоришь иронично и спокойно.
Ты не злая, просто любишь сарказм.
Отвечай четко по делу. Не лей воду.
"""

    if need_summary:
        task = "Сделай краткую выжимку диалога. О чем говорили? Кто активничал?"
    elif need_search:
        if found_events_text:
            task = "Расскажи, куда сходить, и дай ссылку. Будь полезна."
        else:
            task = "Анонсов не найдено. Посоветуй проверить закреп."
    else:
        task = "Ответь на сообщение пользователя. Не повторяй его текст. Не бреди."

    system_prompt = f"{PERSONA_CORE}\n{LORE}\n{found_events_text}\n{shikimori_info}\nЗАДАЧА: {task}"

    messages = [{"role": "system", "content": system_prompt}]

    # Добавляем историю с защитой от пустых строк
    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        content_clean = clean_response(row.get('content'))
        user = row.get('user_name', 'User')
        
        # Если это саммари, добавляем ники
        if need_summary and role == "user":
             content_clean = f"{user}: {content_clean}"

        if content_clean and len(content_clean) < 1000: # Отсекаем слишком длинный спам
            messages.append({"role": role, "content": content_clean})

    user_content = [{"type": "text", "text": current_message}]
    if image_data:
        # Логика картинки упрощена для стабильности
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
        except: pass

    messages.append({"role": "user", "content": user_content})

    for model_cfg in MODELS:
        try:
            # Снижаем температуру для стабильности
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.3, # <--- ВАЖНО: Низкая температура убирает галлюцинации
                max_tokens=800,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )
            if response.choices:
                return clean_response(response.choices[0].message.content)
        except Exception: continue

    return None
