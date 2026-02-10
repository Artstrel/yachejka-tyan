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

async def extract_anime_title(text):
    """Используем маленькую модель, чтобы вытащить чистое название из текста анонса"""
    try:
        messages = [
            {"role": "system", "content": "Твоя задача: найти название аниме, фильма или игры в тексте. Верни ТОЛЬКО название без лишних слов. Если названия нет, верни 'NO'."},
            {"role": "user", "content": f"Текст:\n{text[:1000]}"}
        ]
        response = await client.chat.completions.create(
            model="google/gemma-2-9b-it:free",
            messages=messages,
            temperature=0.1,
            max_tokens=20
        )
        title = response.choices[0].message.content.strip()
        title = re.sub(r"['\"«»]", "", title) # Чистим кавычки
        return title if title != "NO" and len(title) > 2 else None
    except Exception:
        return None

async def generate_response(db, chat_id, current_message, image_data=None):
    # 1. История диалога
    history_rows = await db.get_context(chat_id)
    
    # 2. Поиск анонсов (теперь с лимитом 100!)
    raw_events = await db.get_potential_announcements(chat_id, days=30, limit=100)

    found_events_text = ""
    shikimori_info = ""
    
    # Обработка анонсов
    if raw_events:
        # Сортируем: сначала самые свежие
        # raw_events.sort(key=lambda x: x['timestamp'], reverse=True)
        # Берем топ-5 самых свежих для анализа LLM, чтобы не перегрузить контекст
        top_events = raw_events[:5] 
        
        events_list = []
        full_text_batch = ""
        
        for ev in top_events:
            content = ev['content']
            date = ev.get('timestamp').strftime('%d.%m')
            user = ev['user_name']
            events_list.append(f"--- [POST BY {user} | {date}] ---\n{content}\n")
            full_text_batch += content + "\n"
        
        found_events_text = "\n".join(events_list)

        # 3. Интеграция с Shikimori
        # Если в тексте есть намеки на аниме, пробуем найти инфу
        if re.search(r"(аниме|anime|тайтл|сери|сезон|смотреть|киберслав)", full_text_batch, re.IGNORECASE):
            detected_title = await extract_anime_title(full_text_batch)
            if detected_title:
                logging.info(f"🎬 Найден кандидат: {detected_title}")
                anime_data = await search_anime_info(detected_title)
                
                if anime_data:
                    status_emoji = "🟢" if anime_data['status'] == 'ongoing' else "🔴"
                    shikimori_info = f"""
🧠 ИНФО ИЗ SHIKIMORI:
Название: {anime_data['title']} ({anime_data['original_title']})
Рейтинг: {anime_data['score']} ⭐
Тип: {anime_data['kind']} | {status_emoji} {anime_data['status']}
Эпизоды: {anime_data['episodes']}
Ссылка: {anime_data['url']}
(Добавь эти факты в ответ, если они уместны)
"""

    # === ИТОГОВЫЙ ПРОМПТ ===
    PERSONA = "Ты — Ячейка-тян, ироничный бот-помощник."

    if found_events_text:
        SYSTEM_PROMPT = f"""{PERSONA}

КОНТЕКСТ (Найденные анонсы):
{found_events_text}

{shikimori_info}

ИНСТРУКЦИЯ:
1. Ответь пользователю на вопрос, используя информацию из анонсов.
2. Если есть данные из Shikimori, органично вплети их (например: "Кстати, рейтинг у него 8.5...").
3. Если спрашивают "Где?", указывай локацию точно.
4. Не выдумывай.
"""
    else:
        SYSTEM_PROMPT = f"""{PERSONA}
В базе нет свежих анонсов (я проверила последние 100 сообщений с ключевыми словами).
Ответь: "Пока тихо, свежих анонсов не вижу. Чекайте закреп или спросите админов."
"""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        messages.append({"role": role, "content": clean_response(row['content'])})

    user_content = [{"type": "text", "text": current_message}]
    if image_data:
        # (Код картинки как раньше)
        pass 

    messages.append({"role": "user", "content": user_content})

    for model_cfg in MODELS:
        try:
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.3,
                max_tokens=1000,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )
            if response.choices:
                return clean_response(response.choices[0].message.content)
        except Exception: continue

    return None
