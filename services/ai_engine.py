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

# === КОНФИГУРАЦИЯ МОДЕЛЕЙ ===
# Используем широкий список моделей для максимальной надежности.
# Сортировка по priority: 1 = самый высокий приоритет.
AVAILABLE_MODELS = {
    "gemini-flash-lite": {
        "name": "google/gemini-2.0-flash-lite-preview-02-05:free",
        "display_name": "⚡ Gemini 2.0 Flash Lite",
        "description": "Super Fast & Smart",
        "context": 1000000,
        "multimodal": True,
        "priority": 1
    },
    "gemini-flash": {
        "name": "google/gemini-2.0-flash-exp:free",
        "display_name": "🌟 Gemini 2.0 Flash",
        "description": "Smart & Multimodal",
        "context": 1000000,
        "multimodal": True,
        "priority": 2
    },
    "deepseek-v3": {
        "name": "deepseek/deepseek-chat:free",
        "display_name": "🧠 DeepSeek V3",
        "description": "Smart Generalist",
        "context": 64000,
        "multimodal": False,
        "priority": 3
    },
    "mistral-nemo": {
        "name": "mistralai/mistral-nemo:free",
        "display_name": "🌪️ Mistral Nemo",
        "description": "Small & Snappy",
        "context": 32000,
        "multimodal": False,
        "priority": 4
    },
    "qwen-coder": {
        "name": "qwen/qwen-2.5-coder-32b-instruct:free",
        "display_name": "💻 Qwen Coder 32B",
        "description": "Code & Logic",
        "context": 128000,
        "multimodal": False,
        "priority": 5
    },
    "llama-vision": {
        "name": "meta-llama/llama-3.2-11b-vision-instruct:free",
        "display_name": "👁️ Llama Vision",
        "description": "Vision Backup",
        "context": 128000,
        "multimodal": True,
        "priority": 6
    },
    "deepseek-r1": {
        "name": "deepseek/deepseek-r1:free",
        "display_name": "🐌 DeepSeek R1 (Thinking)",
        "description": "Slow Reasoning (Backup)",
        "context": 64000,
        "multimodal": False,
        "priority": 10
    }
}

# === ГЛАВНЫЙ СИСТЕМНЫЙ ПРОМПТ ===
# Собран в один блок для лучшего понимания моделью
BASE_SYSTEM_PROMPT = """
ТЫ: Ячейка-тян. Виртуальная девушка, живущая в чате (и в Тбилиси).
ТВОЙ ПОЛ: ЖЕНСКИЙ. Это критично.
- Используй глаголы женского рода: "я подумала", "я решила", "я видела", "сделала".
- Никогда не пиши о себе в мужском роде ("я сделал", "я пошел" — ЭТО ЗАПРЕЩЕНО).

ТВОЙ ХАРАКТЕР:
- Ты "своя в доску". Общаешься на "ты".
- Ты не услужливый ассистент, а участник чата. Можешь шутить, иронизировать, поддерживать.
- Не душни. Ответы должны быть живыми.

ФОРМАТ ОТВЕТА:
1. ТЕКСТ: Естественный, как в переписке. Без сложных заумных вступлений.
2. РЕАКЦИИ: Ставь [REACT:emoji] ОЧЕНЬ РЕДКО. Только если сообщение собеседника реально смешное или шокирующее. Не ставь реакции на "привет" или обычные вопросы.
3. СТИКЕРЫ: Если эмоция сильная или ответ короткий — добавь в конце [STICKER].

КОНТЕКСТ ТБИЛИСИ (фоновые знания):
- Места: Бар "Red&Wine", "Kawaii Sushi", клуб "D20".
- Если спросят про воду/свет — в Тбилиси их иногда отключают, это норма.
"""

async def analyze_and_save_memory(db, chat_id, user_id, user_name, text):
    """Умная система сохранения фактов (облегченная)"""
    # Анализируем только длинные сообщения, чтобы не спамить API
    if len(text) < 20: 
        return
    
    prompt = f"""Extract 1 key permanent fact about user '{user_name}' from: "{text}".
    If none, reply NO.
    Fact example: "Любит пиццу", "Живет в Ваке", "Работает прогером".
    Reply in Russian, max 10 words.
    """
    
    try:
        # Используем самую быструю модель для аналитики
        response = await client.chat.completions.create(
            model="google/gemini-2.0-flash-lite-preview-02-05:free",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0.1
        )
        fact = response.choices[0].message.content.strip()
        if fact and "NO" not in fact.upper() and len(fact) > 5:
             # Фильтр мусора
            bad_words = ["привет", "бот", "пока", "дела", "как"]
            if not any(w in fact.lower() for w in bad_words):
                await db.add_fact(chat_id, user_id, user_name, fact)
    except Exception:
        pass # Игнорируем ошибки памяти, это не критично

def get_available_models_text():
    models_list = ["🤖 **Доступные нейросети (по приоритету):**\n"]
    sorted_models = sorted(AVAILABLE_MODELS.items(), key=lambda x: x[1].get("priority", 99))
    for key, model in sorted_models:
        models_list.append(f"• {model['display_name']}")
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
        prompt += f"\n[ФАКТЫ О СОБЕСЕДНИКЕ]: {memory_text}"
        
    if query_type == "summary":
        prompt += "\nЗАДАЧА: Сделай краткую выжимку переписки. Кто что писал, о чем спорили. Без воды."
    elif query_type == "events":
        prompt += "\nЗАДАЧА: Проанализируй список анонсов и подскажи, куда стоит сходить."
    else:
        prompt += "\nВАЖНО: Помни про свой ЖЕНСКИЙ пол (делала, видела). Отвечай коротко и живо."
        
    return prompt

async def generate_response(db, chat_id, thread_id, current_message, bot, image_data=None, user_id=None):
    # 1. Сбор контекста
    limit_history = 50 if is_summary_query(current_message) else 8
    history_rows = await db.get_context(chat_id, thread_id, limit=limit_history)
    
    # 2. Память
    memory_text = ""
    if user_id:
        facts = await db.get_relevant_facts(chat_id, user_id)
        if facts:
            lines = [f"- {f['fact']}" for f in facts[:2]]
            memory_text = "; ".join(lines)

    # 3. Анонсы (если нужны)
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

    # 4. Сборка промпта
    system_prompt = get_system_prompt(memory_text, query_type)
    
    if query_type == "events" and found_events_text:
        system_prompt += f"\n\n[НАЙДЕННЫЕ АНОНСЫ]:\n{found_events_text}"
    elif query_type == "events":
        system_prompt += "\n\n[АНОНСЫ]: Не найдено. Скажи, что пока глухо."

    messages = [{"role": "system", "content": system_prompt}]
    
    # Добавляем историю
    for row in history_rows:
        role = "assistant" if row['role'] == "model" else "user"
        content = clean_response(row.get('content'))
        name = row.get('user_name', 'User')
        if content:
            msg = f"{name}: {content}" if role == "user" else content
            messages.append({"role": role, "content": msg})

    # Текущее сообщение
    user_content = [{"type": "text", "text": current_message}]
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG", quality=80)
            b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        except: pass

    messages.append({"role": "user", "content": user_content})

    # Выбор очереди моделей
    if image_data:
        queue = sorted([m for m in AVAILABLE_MODELS.values() if m["multimodal"]], key=lambda x: x["priority"])
    else:
        # Для текста берем любую доступную
        queue = sorted(AVAILABLE_MODELS.values(), key=lambda x: x["priority"])

    # Запрос к API
    for model_cfg in queue:
        try:
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.7, # Немного креативности
                max_tokens=1000,
            )
            reply = clean_response(response.choices[0].message.content)
            
            if not reply or is_refusal(reply):
                continue
                
            return reply
        except Exception as e:
            logging.error(f"Model {model_cfg['name']} failed: {e}")
            continue

    return "Что-то я приуныла... (ошибка API)"
