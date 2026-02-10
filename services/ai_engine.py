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
    raw_events = await db.get_potential_announcements(chat_id, days=21, limit=5)

    found_events_text = ""
    shikimori_context = ""
    
    if raw_events:
        # 1. Формируем текст анонсов
        events_list = []
        full_text_for_analysis = ""
        
        for ev in raw_events:
            content = ev['content']
            date_str = ev.get('timestamp').strftime('%d.%m')
            user_name = ev['user_name']
            events_list.append(f"--- [POST BY {user_name} | {date_str}] ---\n{content}\n")
            full_text_for_analysis += content + "\n"
        
        found_events_text = "\n".join(events_list)

        # 2. ПОПЫТКА НАЙТИ АНИМЕ ЧЕРЕЗ SHIKIMORI
        # Мы делаем быстрый запрос к LLM, чтобы она выделила название, 
        # потому что Regex тут бессилен.
        try:
            extraction_prompt = [
                {"role": "system", "content": "Твоя задача: найти название аниме или фильма в тексте. Верни ТОЛЬКО название. Если нет - верни 'NO'."},
                {"role": "user", "content": f"Текст анонсов:\n{full_text_for_analysis[:2000]}"} # Ограничиваем длину
            ]
            
            # Используем быструю модель для извлечения
            extractor = await client.chat.completions.create(
                model="google/gemma-2-9b-it:free",
                messages=extraction_prompt,
                temperature=0.1,
                max_tokens=20
            )
            
            title_candidate = extractor.choices[0].message.content.strip()
            
            if title_candidate and title_candidate != "NO" and len(title_candidate) > 2:
                # Если нашли название -> идем в Shikimori
                logging.info(f"🔎 Detected Anime Title: {title_candidate}. Searching Shikimori...")
                anime_data = await search_anime_info(title_candidate)
                
                if anime_data:
                    shikimori_context = f"""
🧠 ДАННЫЕ ИЗ БАЗЫ SHIKIMORI (ДЛЯ СПРАВКИ):
Название: {anime_data['title']}
Рейтинг: {anime_data['score']} ⭐
Тип: {anime_data['kind']} ({anime_data['status']})
Эпизодов: {anime_data['episodes']}
Ссылка: {anime_data['url']}
(Используй эту инфу, чтобы рассказать подробнее, если уместно)
"""
        except Exception as e:
            logging.error(f"Extraction error: {e}")

    # === ОСНОВНОЙ ПРОМПТ ===
    
    PERSONA = """
Ты — Ячейка-тян, бот-помощник. Характер: ироничная, полезная, "своя в доску".
Твоя задача — анализировать анонсы и отвечать на вопросы.
"""

    if found_events_text:
        SYSTEM_PROMPT = f"""{PERSONA}

КОНТЕКСТ СООБЩЕНИЙ ЧАТА:
{found_events_text}

{shikimori_context}

ИНСТРУКЦИЯ:
1. Если спрашивают про мероприятия, расскажи детали (что, где, когда).
2. Если мы нашли инфу на Shikimori, обязательно добавь рейтинг и ссылку на аниме.
3. Если инфы на Shikimori нет, просто опирайся на текст сообщений.
4. Не выдумывай факты.
"""
    else:
        SYSTEM_PROMPT = f"""{PERSONA}
В базе нет свежих закрепленных анонсов.
Если спросят "куда сходить", ответь, что пока тихо, но можно спросить у админов.
Не говори, что "все спились", если только это не шутка в контексте.
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
        model_name = model_cfg["name"]
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.3,
                max_tokens=1000,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )

            if response.choices and response.choices[0].message.content:
                final_text = clean_response(response.choices[0].message.content)
                if not final_text: continue
                return final_text

        except Exception as e:
            continue

    return None
