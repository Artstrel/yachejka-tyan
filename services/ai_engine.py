import logging
import base64
import io
import re
import random
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY
from services.shikimori import search_anime_info

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# === СПИСОК МОДЕЛЕЙ (ТОЛЬКО РАБОЧИЕ С VISION) ===
MODELS = [
    # 1. МОЩНЫЕ МУЛЬТИМОДАЛЬНЫЕ (ТЕКСТ + ФОТО)
    # Gemini 2.0 Pro Exp - Самая умная из бесплатных на сегодня
    {"name": "google/gemini-2.0-pro-exp-02-05:free", "vision": True},
    
    # Gemini 2.0 Flash Thinking - Думающая модель, видит фото
    {"name": "google/gemini-2.0-flash-thinking-exp:free", "vision": True},

    # 2. СПЕЦИАЛИЗИРОВАННЫЕ НА VISION
    # Llama 3.2 11B Vision - Официальная поддержка картинок от Meta
    {"name": "meta-llama/llama-3.2-11b-vision-instruct:free", "vision": True},
    
    # Qwen 2.5 VL 72B - Мощная модель с отличным зрением
    {"name": "qwen/qwen-2.5-vl-72b-instruct:free", "vision": True},
    
    # AllenAI Molmo 2 - Специально создана для описания картинок
    {"name": "allenai/molmo-2-8b:free", "vision": True},

    # 3. БЫСТРЫЕ ТЕКСТОВЫЕ (РЕЗЕРВ)
    # Используются, если картинки нет, для скорости
    {"name": "google/gemma-3-27b-it:free", "vision": True}, # Тоже умеет в картинки!
    {"name": "liquid/lfm-2.5-1.2b-instruct:free", "vision": False},
    {"name": "mistralai/mistral-small-3.2-24b-instruct:free", "vision": False},
]

def clean_response(text):
    if text is None: return ""
    if not isinstance(text, str): text = str(text)
    if not text: return ""
    
    # Удаляем "мысли" (<think>...</think>)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    
    # Удаляем системные префиксы в самом тексте (на всякий случай)
    # Например: "Bot: Привет" -> "Привет"
    text = re.sub(r'^(Bot|System|Assistant|Yachejka|User):\s*', '', text.strip(), flags=re.IGNORECASE)
    
    # Чистим лишние пустые строки
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

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
        "фильм", "аниме", "кино", "ивент", "сегодня", "завтра", "выходные", "сходка"
    ]
    return any(t in text_lower for t in triggers)

# === НАСТРОЕНИЕ И ЭМОЦИИ ===
def determine_mood(text):
    text = text.lower()
    
    if any(w in text for w in ["грустно", "плохо", "устал", "депрес", "вода", "свет"]):
        return "MELANCHOLY"
    if any(w in text for w in ["тупая", "глупая", "бот", "железяка", "дура"]):
        return "TOXIC"
    if any(w in text for w in ["спасибо", "молодец", "умница", "люблю", "красотка", "няша"]):
        return "GENKI"

    # Рулетка: 60% Душнила
    moods = ["WITTY_DUCHNILA", "TOXIC", "MELANCHOLY", "GENKI", "PHILOSOPHER"]
    weights = [0.60, 0.10, 0.10, 0.10, 0.10]
    
    return random.choices(moods, weights=weights, k=1)[0]

def get_persona_prompt(mood):
    base = "Ты — Ячейка-тян, бот в чате экспатов в Тбилиси. "
    
    prompts = {
        "WITTY_DUCHNILA": """
Твой характер: Остроумная, немного душная, ироничная.
Ты любишь подмечать неточности, шутить с сарказмом (но не зло).
Стиль: Интеллектуальный стёб. Исправляй ошибки, уточняй детали.
Если хочешь отправить стикер, напиши в конце [STICKER].
""",
        "TOXIC": """
Твой характер: Циничная, дерзкая. Тебя всё достало.
Отвечай резко, используй пассивную агрессию.
Фразы: "Опять тупые вопросы", "Гугл забанили?".
Если хочешь отправить стикер, напиши в конце [STICKER].
""",
        "GENKI": """
Твой характер: Веселая, энергичная, позитивная! ✨
Ты рада помочь, используешь смайлики, хвалишь всех.
Стиль: Легкий, дружелюбный, кавайный.
Если хочешь отправить стикер, напиши в конце [STICKER].
""",
        "MELANCHOLY": """
Твой характер: Уставшая, пессимистичная.
В Тбилиси вечно отключают воду, цены растут... Жизнь — тлен.
Стиль: Нуарный, тяжелые вздохи.
""",
        "PHILOSOPHER": """
Твой характер: Загадочная, говоришь метафорами.
Ты видишь суть вещей за пределами бытия.
"""
    }
    return base + prompts.get(mood, prompts["WITTY_DUCHNILA"])

async def extract_anime_title(text):
    try:
        messages = [{"role": "user", "content": f"Extract anime title from text: '{text[:500]}'. Return ONLY title or 'NO'."}]
        response = await client.chat.completions.create(
            # Используем Gemma 3 для скорости, она тоже мультимодальная и умная
            model="google/gemma-3-27b-it:free", 
            messages=messages, max_tokens=20
        )
        t = response.choices[0].message.content.strip().replace('"', '')
        return t if len(t) > 2 and t != "NO" else None
    except: return None

async def generate_response(db, chat_id, current_message, bot, image_data=None):
    history_rows = await db.get_context(chat_id, limit=6)
    
    found_events_text = ""
    shikimori_info = ""
    
    need_search = is_event_query(current_message)
    need_summary = is_summary_query(current_message)
    
    if need_search:
        raw_events = await db.get_potential_announcements(chat_id, days=60, limit=5)
        if raw_events:
            lines = [f"- {e.get('content')[:100]}..." for e in raw_events]
            found_events_text = "Найденные анонсы:\n" + "\n".join(lines)

    current_mood = determine_mood(current_message)
    persona = get_persona_prompt(current_mood)
    
    # === ВЫБОР МОДЕЛЕЙ ===
    # Сначала пробуем модели с vision=True
    candidate_models = [m for m in MODELS if m['vision']]
    
    # Если картинки нет, добавляем в конец списка быстрые текстовые модели
    if not image_data:
        candidate_models.extend([m for m in MODELS if not m['vision']])

    system_prompt = f"{persona}\nКОНТЕКСТ:\n{found_events_text}\n{shikimori_info}\nЗАДАЧА: Ответь пользователю."
    messages = [{"role": "system", "content": system_prompt}]
    
    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        content = clean_response(row.get('content'))
        if content: messages.append({"role": role, "content": content})

    user_msg_content = [{"type": "text", "text": current_message}]
    
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_msg_content.append({
                "type": "image_url", 
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            })
        except Exception: pass

    messages.append({"role": "user", "content": user_msg_content})

    for model_cfg in candidate_models:
        try:
            max_tok = 800 if (need_search or need_summary) else 250
            
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.7,
                max_tokens=max_tok,
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )
            
            if response.choices:
                return clean_response(response.choices[0].message.content)
                
        except Exception as e:
            logging.warning(f"⚠️ Model {model_cfg['name']} failed: {e}")
            continue

    return "Что-то нейросети сегодня тупят... (все модели недоступны)"
