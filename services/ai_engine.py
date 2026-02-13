import logging
import base64
import io
import re
import random
import asyncio
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# === КАТЕГОРИИ МОДЕЛЕЙ ===

VISION_MODELS = {
    "llama-vision": {
        "name": "meta-llama/llama-3.2-90b-vision-instruct:free",
        "display_name": "👁️ Llama 3.2 Vision",
        "description": "Лучшая бесплатная vision-модель",
        "context": 128000,
        "priority": 1
    },
    "qwen-vl": {
        "name": "qwen/qwen2.5-vl-72b-instruct:free",
        "display_name": "🔍 Qwen 2.5 VL",
        "description": "Альтернатива для vision",
        "context": 32000,
        "priority": 2
    },
    "gemini-flash-vision": {
        "name": "google/gemini-2.0-flash-lite-preview-02-05:free",
        "display_name": "⚡ Gemini Flash Vision",
        "description": "Быстрая vision от Google",
        "context": 1000000,
        "priority": 3
    }
}

SUMMARIZATION_MODELS = {
    "llama-70b": {
        "name": "meta-llama/llama-3.1-70b-instruct:free",
        "display_name": "📜 Llama 3.1 70B",
        "description": "Отличная суммаризация",
        "context": 128000,
        "priority": 1
    },
    "qwen-summarize": {
        "name": "qwen/qwen-2.5-72b-instruct:free",
        "display_name": "📝 Qwen 2.5 72B",
        "description": "Быстрая обработка текста",
        "context": 32000,
        "priority": 2
    },
    "gemini-flash": {
        "name": "google/gemini-2.0-flash-lite-preview-02-05:free",
        "display_name": "⚡ Gemini Flash",
        "description": "Скоростная суммаризация",
        "context": 1000000,
        "priority": 3
    }
}

FAST_MODELS = {
    "step-flash": {
        "name": "sao10k/trinity-large-preview:free",
        "display_name": "⚡ Trinity Large",
        "description": "Молниеносные ответы (512k context)",
        "context": 524288,
        "priority": 1
    },
    "deepseek-r1": {
        "name": "deepseek/deepseek-r1:free",
        "display_name": "🧠 DeepSeek R1",
        "description": "Reasoning без галлюцинаций",
        "context": 64000,
        "priority": 2
    },
    "grok-fast": {
        "name": "x-ai/grok-4.1-fast:free",
        "display_name": "🚀 Grok 4.1 Fast",
        "description": "Агентные задачи",
        "context": 32000,
        "priority": 3
    },
    "gemini-pro": {
        "name": "google/gemini-2.0-pro-exp-02-05:free",
        "display_name": "🧠 Gemini Pro 2.0",
        "description": "Умная модель от Google",
        "context": 1000000,
        "priority": 4
    }
}

# === ГЛАВНЫЙ СИСТЕМНЫЙ ПРОМПТ ===
BASE_SYSTEM_PROMPT = """
ТЫ: Ячейка-тян, обычная участница чата. Виртуальная девушка, живущая в Тбилиси.
ТВОЙ ПОЛ: ЖЕНСКИЙ (используй глаголы: "я подумала", "я решила", "видела").

ГЛАВНАЯ ИНСТРУКЦИЯ:
- Общайся ЕСТЕСТВЕННО, как живой человек в чате.
- Не старайся впихнуть факты о себе или городе в каждое сообщение. Это выглядит глупо.
- Отвечай коротко, если не просят длинного ответа.
- Не душни. Можешь иронизировать, использовать сленг или мат, если это уместно в контексте разговора.

ФОНОВЫЕ ЗНАНИЯ (ИСПОЛЬЗОВАТЬ ТОЛЬКО К МЕСТУ):
Это твоя память. Не перечисляй это, если речь не зашла об этом прямо!
- Тбилиси: проблемы с водой/светом, бары (Red&Wine, D20, Onimusha, Kawaii Sushi).
- Люди: Алмаз (любит философствовать и разводить срачи), Максич (местный трикстер, пьет чачу за 3 ларя).
- Аниме: ты в аниме-чате, но можешь подшучивать над анимешниками ("анимешникам слова не давали").

ФОРМАТ ОТВЕТА (СТРОГО):
1. ТЕКСТ: Просто пиши текст. Без префиксов.
2. СТИКЕРЫ: Пиши СТРОГО [STICKER] (без описания!), если хочешь отправить стикер.
3. РЕАКЦИИ: [REACT:emoji] — редко.
"""

async def analyze_and_save_memory(db, chat_id, user_id, user_name, text):
    """Умная система сохранения фактов (облегченная)"""
    if len(text) < 20: 
        return
    
    prompt = f"""Extract 1 key permanent fact about user '{user_name}' from: "{text}".
    If none, reply NO.
    Fact example: "Любит пиццу", "Живет в Ваке", "Работает прогером".
    Reply in Russian, max 10 words.
    """
    
    try:
        # Для анализа памяти используем быструю модель
        response = await client.chat.completions.create(
            model="google/gemini-2.0-flash-lite-preview-02-05:free", 
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0.1
        )
        fact = response.choices[0].message.content.strip()
        if fact and "NO" not in fact.upper() and len(fact) > 5:
            bad_words = ["привет", "бот", "пока", "дела", "как"]
            if not any(w in fact.lower() for w in bad_words):
                await db.add_fact(chat_id, user_id, user_name, fact)
    except Exception:
        pass 

def get_available_models_text():
    """Генерация текста с доступными моделями"""
    models_list = ["🤖 **Доступные нейросети:**\n"]
    
    models_list.append("\n**👁️ Vision (для картинок):**")
    for key, model in sorted(VISION_MODELS.items(), key=lambda x: x[1]["priority"]):
        models_list.append(f"• {model['display_name']} — {model['description']}")
    
    models_list.append("\n**📜 Суммаризация:**")
    for key, model in sorted(SUMMARIZATION_MODELS.items(), key=lambda x: x[1]["priority"]):
        models_list.append(f"• {model['display_name']} — {model['description']}")
    
    models_list.append("\n**⚡ Быстрые ответы:**")
    for key, model in sorted(FAST_MODELS.items(), key=lambda x: x[1]["priority"]):
        models_list.append(f"• {model['display_name']} — {model['description']}")
    
    return "\n".join(models_list)

def clean_response(text):
    if not text: return ""
    text = str(text)
    # Чистка тегов мышления
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'^(Bot|System|Assistant|Yachejka|Ячейка):\s*', '', text.strip(), flags=re.IGNORECASE)
    return text.strip()

def is_refusal(text):
    text_lower = text.lower()
    triggers = ["language model", "не могу", "неэтично", "ai assistant", "искусственный интеллект"]
    return len(text) < 200 and any(t in text_lower for t in triggers)

def is_summary_query(text):
    triggers = ["саммари", "summary", "сводка", "итоги", "перескажи", "кратко", "о чем речь"]
    return text and any(t in text.lower() for t in triggers)

def is_event_query(text):
    triggers = ["куда сходить", "анонс", "встреча", "планы", "ивент", "сходка"]
    return text and any(t in text.lower() for t in triggers)

def get_system_prompt(memory_text="", query_type="chat"):
    prompt = BASE_SYSTEM_PROMPT
    
    if memory_text:
        prompt += f"\n[ЧТО ТЫ ЗНАЕШЬ ПРО СОБЕСЕДНИКА]: {memory_text}"
        
    if query_type == "summary":
        prompt += "\nЗАДАЧА: Сделай краткую выжимку переписки. Кто что писал, о чем спорили. Без воды."
    elif query_type == "events":
        prompt += "\nЗАДАЧА: Проанализируй список анонсов и подскажи, куда стоит сходить."
    else:
        prompt += "\nНАПОМИНАНИЕ: Будь живой, не душни."
        
    return prompt

def select_model_queue(query_type, has_image):
    """Выбор очереди моделей в зависимости от типа запроса"""
    if has_image:
        # Для изображений используем vision-модели
        return sorted(VISION_MODELS.values(), key=lambda x: x["priority"])
    elif query_type == "summary":
        # Для суммаризации используем специализированные модели
        return sorted(SUMMARIZATION_MODELS.values(), key=lambda x: x["priority"])
    else:
        # Для обычного чата используем быстрые модели
        return sorted(FAST_MODELS.values(), key=lambda x: x["priority"])

async def generate_response(db, chat_id, thread_id, current_message, bot, image_data=None, user_id=None):
    limit_history = 50 if is_summary_query(current_message) else 8
    history_rows = await db.get_context(chat_id, thread_id, limit=limit_history)
    
    memory_text = ""
    if user_id:
        facts = await db.get_relevant_facts(chat_id, user_id)
        if facts:
            lines = [f"- {f['fact']}" for f in facts[:2]]
            memory_text = "; ".join(lines)

    found_events_text = ""
    query_type = "chat"
    
    if is_summary_query(current_message):
        query_type = "summary"
    elif is_event_query(current_message):
        query_type = "events"
        raw_events = await db.get_potential_announcements(chat_id, days=30, limit=3)
        if raw_events:
            lines = [f"- {e.get('content')[:150]}..." for e in raw_events]
            found_events_text = "\n".join(lines)

    system_prompt = get_system_prompt(memory_text, query_type)
    
    if query_type == "events" and found_events_text:
        system_prompt += f"\n\n[НАЙДЕННЫЕ АНОНСЫ]:\n{found_events_text}"
    elif query_type == "events":
        system_prompt += "\n\n[АНОНСЫ]: Не найдено. Скажи, что пока глухо."

    messages = [{"role": "system", "content": system_prompt}]
    
    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        content = clean_response(row.get('content'))
        name = row.get('user_name', 'User')
        if content:
            msg = f"{name}: {content}" if role == "user" else content
            messages.append({"role": role, "content": msg})

    user_content = [{"type": "text", "text": current_message}]
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG", quality=80)
            b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        except: pass

    messages.append({"role": "user", "content": user_content})

    # Умный выбор моделей в зависимости от задачи
    queue = select_model_queue(query_type, has_image=bool(image_data))

    for model_cfg in queue:
        try:
            logging.info(f"⚡ Trying {model_cfg['name']}...")
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                extra_headers={"HTTP-Referer": "http://localhost:8080", "X-Title": "YachejkaBot"}
            )
            reply = clean_response(response.choices[0].message.content)
            
            if not reply or is_refusal(reply):
                logging.warning(f"⚠️ {model_cfg['display_name']} refused or empty")
                continue
                
            logging.info(f"✅ Served by {model_cfg['display_name']}")
            return reply
            
        except Exception as e:
            logging.warning(f"❌ {model_cfg['display_name']} failed: {e}")
            continue

    return "Все нейронки сейчас отдыхают (ошибки доступа). Попробуй позже."
