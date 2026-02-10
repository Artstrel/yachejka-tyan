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
    
    # Получаем анонсы (теперь с улучшенным поиском из db.py)
    raw_events = await db.get_potential_announcements(chat_id, days=21, limit=5)

    found_events_text = ""
    has_relevant_info = False
    
    if raw_events:
        events_list = []
        for ev in raw_events:
            content = ev['content']
            # Добавляем дату сообщения, чтобы бот понимал, про какой год/месяц речь,
            # если в тексте написано просто "в эту субботу"
            msg_date = ev.get('timestamp').strftime('%d.%m.%Y')
            user = ev.get('user_name', 'Anon')
            events_list.append(f"--- [СООБЩЕНИЕ ОТ {msg_date} | User: {user}] ---\n{content}\n")
        
        found_events_text = "\n".join(events_list)
        has_relevant_info = True

    # === ДИНАМИЧЕСКИЙ ПРОМПТ ===
    
    # Базовая личность (без перегибов)
    PERSONA = """
Ты — Ячейка-тян, бот-помощник для аниме-сообщества в Тбилиси.
Твой характер: ироничная, немного уставшая экспатка, но полезная. Ты не хамишь без повода.
Твоя главная цель — помогать людям находить информацию о встречах (Ячейках).
"""

    if has_relevant_info:
        # Промпт, когда анонсы НАЙДЕНЫ. Учим структуру твоих сообщений.
        SYSTEM_PROMPT = f"""{PERSONA}

КОНТЕКСТ: Ниже приведены последние сообщения из чата, которые похожи на анонсы мероприятий.
Твоя задача — проанализировать их и ответить на вопрос пользователя.

ВАЖНО: Анонсы пишут люди в свободном стиле. Вот как их понимать (ПРИМЕРЫ):
1. "Суббота - 07.02 - 19:00 (everyweek) ... Место - Bar d22" -> Это анонс на 7 февраля в 19:00 в баре D22.
2. "PowerPoint Ячейка! ‼️ 28 февраля 19:30 | D22 Bar" -> Это анонс PowerPoint тусовки.
3. "Кровь на часовой башне... 19 декабря пятница... в Red&Wine" -> Игротека в Red&Wine.
4. "Вход везде бесплатный! Напитки платные!" -> Условия входа.

НАЙДЕННЫЕ СООБЩЕНИЙ В БАЗЕ:
{found_events_text}

ИНСТРУКЦИЯ:
1. Если пользователь спрашивает "Куда сходить?" или "Что будет?", составь список всех АКТУАЛЬНЫХ мероприятий из найденных текстов.
2. Игнорируй мероприятия, даты которых уже прошли (сравнивай с текущей датой).
3. Формат ответа сделай читаемым (используй смайлики 📅, 📍, 💰).
4. НЕ выдумывай мероприятия, которых нет в тексте. Если текст непонятен — так и скажи.
5. НЕ используй старые локальные мемы (Жабабот, Максич), если они не упоминаются в новых сообщениях.
"""
    else:
        # Промпт, когда анонсов НЕТ.
        SYSTEM_PROMPT = f"""{PERSONA}

КОНТЕКСТ: Ты поискала в базе сообщений, но не нашла свежих анонсов мероприятий.

ИНСТРУКЦИЯ:
1. Если спрашивают про мероприятия, ответь честно: "Пока не вижу закрепленных анонсов. Попробуйте чекнуть закрепленные сообщения или спросить у админов."
2. Можешь пошутить (в стиле: "Видимо, организаторы в спячке" или "В Тбилиси слишком хорошая погода, чтобы сидеть в чате"), но НЕ говори, что все умерли или спились.
3. Не придумывай несуществующие встречи.
"""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Добавляем историю переписки
    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        clean_content = clean_response(row['content'])
        messages.append({"role": role, "content": clean_content})

    # Текущее сообщение
    user_content = [{"type": "text", "text": current_message}]
    
    # Обработка картинки (если есть)
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        except Exception:
            pass # Если картинка битая, игнорируем

    messages.append({"role": "user", "content": user_content})

    # Перебор моделей
    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.3, # Ставим ниже (было 0.4), чтобы меньше фантазировал
                max_tokens=1000,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )

            if response.choices and response.choices[0].message.content:
                final_text = clean_response(response.choices[0].message.content)
                if not final_text: continue
                return final_text

        except Exception as e:
            logging.error(f"Model {model_name} failed: {e}")
            continue

    return None
