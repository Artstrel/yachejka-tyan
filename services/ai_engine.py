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

async def extract_anime_title(text):
    """
    Использует дешевую модель, чтобы вытащить название аниме из текста анонса.
    """
    try:
        messages = [
            {"role": "system", "content": "Твоя задача: найти название аниме, фильма или игры в тексте. Верни ТОЛЬКО название (на русском или английском). Если явного названия нет, верни 'NO'."},
            {"role": "user", "content": f"Текст:\n{text[:500]}"}
        ]
        response = await client.chat.completions.create(
            model="google/gemma-2-9b-it:free", # Быстрая и бесплатная модель
            messages=messages,
            temperature=0.1,
            max_tokens=20
        )
        title = response.choices[0].message.content.strip()
        # Чистим от кавычек и лишнего
        title = re.sub(r"['\"«»]", "", title)
        return title if title != "NO" and len(title) > 2 else None
    except Exception as e:
        logging.error(f"Title extraction failed: {e}")
        return None

async def generate_response(db, chat_id, current_message, image_data=None):
    # 1. Получаем контекст диалога (последние 10 сообщений)
    history_rows = await db.get_context(chat_id)
    
    # 2. Ищем анонсы за 21 день (БЕЗ лимита в 10 сообщений, поиск по базе)
    raw_events = await db.get_potential_announcements(chat_id, days=21, limit=5)

    found_events_text = ""
    shikimori_info_block = ""
    
    if raw_events:
        events_list = []
        full_text_batch = ""
        
        for ev in raw_events:
            content = ev['content']
            date_str = ev.get('timestamp').strftime('%d.%m')
            user_name = ev['user_name']
            events_list.append(f"--- [POST BY {user_name} | {date_str}] ---\n{content}\n")
            full_text_batch += content + "\n"
        
        found_events_text = "\n".join(events_list)

        # 3. ПОПЫТКА ИНТЕГРАЦИИ SHIKIMORI
        # Если в найденных анонсах есть слова "аниме", "тайтл" и т.д., пробуем найти инфо
        if re.search(r"(аниме|anime|тайтл|сери|сезон)", full_text_batch, re.IGNORECASE):
            detected_title = await extract_anime_title(full_text_batch)
            
            if detected_title:
                logging.info(f"🎬 Найден кандидат на название: {detected_title}")
                anime_data = await search_anime_info(detected_title)
                
                if anime_data:
                    status_icon = "🟢" if anime_data['status'] == 'ongoing' else "🔴"
                    shikimori_info_block = f"""
🧠 ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ ИЗ SHIKIMORI (Для справки):
Название: {anime_data['title']} ({anime_data['original_title']})
Рейтинг: {anime_data['score']} ⭐
Тип: {anime_data['kind']} | Статус: {status_icon} {anime_data['status']}
Эпизоды: {anime_data['episodes']}
Ссылка: {anime_data['url']}
(Используй эти данные, чтобы дополнить ответ, если они подходят по контексту)
"""

    # === ФОРМИРОВАНИЕ ПРОМПТА ===
    
    PERSONA = """
Ты — Ячейка-тян, бот-помощник аниме-сообщества.
Твой стиль: дружелюбный, но с легкой иронией. Ты любишь конкретику.
"""

    if found_events_text:
        SYSTEM_PROMPT = f"""{PERSONA}

КОНТЕКСТ: Ниже найдены последние сообщения, похожие на анонсы мероприятий.
Твоя задача — прочитать их и ответить пользователю.

{shikimori_info_block}

НАЙДЕННЫЕ СООБЩЕНИЯ:
{found_events_text}

ИНСТРУКЦИЯ:
1. Выдели суть мероприятия: Что? Где? Когда?
2. Если мы нашли данные на Shikimori (рейтинг, эпизоды), обязательно добавь их в ответ красиво.
3. Если данных Shikimori нет, просто перескажи анонс.
4. Указывай локацию точно (если D22 — пиши адрес 4 Amaghleba St).
5. Не выдумывай того, чего нет в тексте.
"""
    else:
        SYSTEM_PROMPT = f"""{PERSONA}
В базе данных за последние 3 недели не найдено сообщений, похожих на анонсы (с датами, временем или локациями).
Если спрашивают "Куда сходить?", честно скажи: "Пока тихо, свежих анонсов не вижу. Может, спросить у админов?"
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
        except Exception: pass

    messages.append({"role": "user", "content": user_content})

    for model_cfg in MODELS:
        try:
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.3,
                max_tokens=1200,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )
            if response.choices and response.choices[0].message.content:
                return clean_response(response.choices[0].message.content)
        except Exception: continue

    return None
