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

# === ТВОЯ КОНФИГУРАЦИЯ МОДЕЛЕЙ (С ДОПОЛНЕНИЯМИ) ===
AVAILABLE_MODELS = {
    # --- ТВОЙ СПИСОК (TEXT / REASONING) ---
    "aurora": {
        "name": "openrouter/aurora-alpha",
        "display_name": "🌟 Aurora Alpha",
        "description": "Быстрая reasoning модель (8B)",
        "context": 128000,
        "multimodal": False
    },
    "step": {
        "name": "stepfun/step-3.5-flash-free", # Поправил ID на актуальный для OpenRouter
        "display_name": "⚡ Step 3.5 Flash",
        "description": "Мощная MoE модель (196B)",
        "context": 256000,
        "multimodal": False
    },
    "trinity": {
        "name": "arcee-ai/trinity-large-preview-free", # Поправил ID
        "display_name": "💎 Trinity Large",
        "description": "Креатив и ролеплей (400B)",
        "context": 131000,
        "multimodal": False
    },
    "liquid-thinking": {
        "name": "liquid/lfm-2.5-1.2b-thinking-free", # Поправил ID
        "display_name": "🧠 Liquid Thinking",
        "description": "Легкая reasoning (1.2B)",
        "context": 33000,
        "multimodal": False
    },
    "liquid-instruct": {
        "name": "liquid/lfm-2.5-1.2b-instruct-free", # Поправил ID
        "display_name": "💬 Liquid Instruct",
        "description": "Ультра-быстрая чат-модель",
        "context": 33000,
        "multimodal": False
    },
    "solar": {
        "name": "upstage/solar-pro-3-free", # Поправил ID
        "display_name": "☀️ Solar Pro 3",
        "description": "Корейский/Японский фокус",
        "context": 128000,
        "multimodal": False,
        "note": "Удалят 02.03.2026"
    },

    # --- ДОБАВЛЕННЫЕ МНОЮ (VISION / КАРТИНКИ) ---
    # Без них бот ослепнет
    "gemini-exp": {
        "name": "google/gemini-2.0-pro-exp-02-05:free",
        "display_name": "👁️ Gemini 2.0 Pro",
        "description": "Топ для картинок и логики",
        "context": 2000000,
        "multimodal": True
    },
    "llama-vision": {
        "name": "meta-llama/llama-3.2-11b-vision-instruct:free",
        "display_name": "👁️ Llama 3.2 Vision",
        "description": "Стабильная vision модель",
        "context": 128000,
        "multimodal": True
    }
}

# Модель по умолчанию (Как ты хотел)
DEFAULT_MODEL_KEY = "aurora"

def get_available_models_text():
    """Возвращает красивый список моделей для команды /models"""
    text = "🤖 **Доступные нейросети:**\n"
    for key, model in AVAILABLE_MODELS.items():
        mode = "🖼️ Vision" if model["multimodal"] else "📝 Text"
        text += f"\n`{key}` — {model['display_name']}\nRunning: {model['description']} [{mode}]"
    return text

def clean_response(text):
    if not text: return ""
    text = str(text)
    # Удаляем теги мышления (Aurora, Liquid Thinking, DeepSeek)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Удаляем системный мусор
    text = re.sub(r'^(Bot|System|Assistant|Yachejka|User):\s*', '', text.strip(), flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def is_summary_query(text):
    if not text: return False
    triggers = ["что тут происходит", "о чем речь", "кратко перескажи", "саммари", "summary", "сводка", "итоги"]
    return any(t in text.lower() for t in triggers)

def is_event_query(text):
    if not text: return False
    triggers = ["куда сходить", "анонс", "встреча", "когда", "во сколько", "фильм", "аниме", "кино", "ивент", "сходка"]
    return any(t in text.lower() for t in triggers)

# === НАСТРОЕНИЕ (Оставили твою логику) ===
def determine_mood(text):
    text = text.lower()
    if any(w in text for w in ["грустно", "плохо", "устал", "депрес", "вода", "свет"]): return "MELANCHOLY"
    if any(w in text for w in ["тупая", "глупая", "бот", "железяка"]): return "TOXIC"
    if any(w in text for w in ["спасибо", "молодец", "умница", "люблю"]): return "GENKI"
    return random.choices(
        ["WITTY_DUCHNILA", "TOXIC", "MELANCHOLY", "GENKI", "PHILOSOPHER"], 
        weights=[0.60, 0.10, 0.10, 0.10, 0.10], k=1
    )[0]

def get_persona_prompt(mood):
    # (Твой промпт из прошлых шагов - сократил для краткости, он тот же)
    base = "Ты — Ячейка-тян, бот в чате экспатов в Тбилиси. "
    prompts = {
        "WITTY_DUCHNILA": "Твой характер: Остроумная, немного душная. Стиль: Интеллектуальный стёб.",
        "TOXIC": "Твой характер: Циничная, дерзкая. Фразы: 'Гугл забанили?'.",
        "GENKI": "Твой характер: Веселая, позитивная! ✨",
        "MELANCHOLY": "Твой характер: Уставшая, пессимистичная. Жизнь — тлен.",
        "PHILOSOPHER": "Твой характер: Загадочная, говоришь метафорами."
    }
    suffix = "\nЕсли хочешь отправить стикер, напиши в конце [STICKER]."
    return base + prompts.get(mood, prompts["WITTY_DUCHNILA"]) + suffix

# === ГЛАВНАЯ ФУНКЦИЯ ГЕНЕРАЦИИ ===
async def generate_response(db, chat_id, current_message, bot, image_data=None):
    history_rows = await db.get_context(chat_id, limit=6)
    
    # Сбор контекста (анонсы)
    found_events_text = ""
    if is_event_query(current_message):
        raw_events = await db.get_potential_announcements(chat_id, days=60, limit=5)
        if raw_events:
            lines = [f"- {e.get('content')[:100]}..." for e in raw_events]
            found_events_text = "Найденные анонсы:\n" + "\n".join(lines)

    current_mood = determine_mood(current_message)
    persona = get_persona_prompt(current_mood)
    
    # === ФОРМИРОВАНИЕ ОЧЕРЕДИ МОДЕЛЕЙ ===
    # Мы создаем список приоритетов.
    priority_queue = []

    if image_data:
        # 1. Если КАРТИНКА -> Только Vision модели
        priority_queue = [m for m in AVAILABLE_MODELS.values() if m["multimodal"]]
    else:
        # 2. Если ТЕКСТ -> Сначала твоя Default (Aurora), потом остальные
        default = AVAILABLE_MODELS.get(DEFAULT_MODEL_KEY)
        if default: priority_queue.append(default)
        
        # Добавляем остальные (Step, Trinity...) как запасные
        for k, m in AVAILABLE_MODELS.items():
            if k != DEFAULT_MODEL_KEY and not m["multimodal"]:
                priority_queue.append(m)

    # Промпт
    system_prompt = f"{persona}\nКОНТЕКСТ:\n{found_events_text}\nЗАДАЧА: Ответь пользователю."
    messages = [{"role": "system", "content": system_prompt}]
    
    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        content = clean_response(row.get('content'))
        if content: messages.append({"role": role, "content": content})

    user_msg_content = [{"type": "text", "text": current_message}]
    
    # Обработка картинки для API
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_msg_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        except: pass

    messages.append({"role": "user", "content": user_msg_content})

    # === ЦИКЛ ПЕРЕБОРА (FALLBACK) ===
    # Если Aurora упадет, бот автоматически попробует Step, потом Trinity и т.д.
    for model_cfg in priority_queue:
        try:
            max_tok = 800 if (is_event_query(current_message) or is_summary_query(current_message)) else 300
            
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
            logging.warning(f"⚠️ Model {model_cfg['display_name']} failed: {e}")
            continue # Пробуем следующую модель в списке

    return "Что-то нейросети сегодня тупят... (все модели недоступны)"
