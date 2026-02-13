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
# Оптимизированные free-модели для лучшей точности и скорости
AVAILABLE_MODELS = {
    # --- ОСНОВНЫЕ БЫСТРЫЕ ТЕКСТОВЫЕ ---
    "aurora-alpha": {
        "name": "openrouter/aurora-alpha",
        "display_name": "🚀 Aurora Alpha",
        "description": "Fast conversational + coding (10.7B, 128K ctx)",
        "context": 128000,
        "multimodal": False,
        "priority": 1,  # ОСНОВНАЯ для повседневного чата
    },
    "step-flash": {
        "name": "stepfun/step-3.5-flash:free",
        "display_name": "⚡ Step 3.5 Flash",
        "description": "Complex queries, ultra-fast (182B MoE, 256K ctx)",
        "context": 256000,
        "multimodal": False,
        "priority": 2,  # для сложных запросов
    },
    
    # --- УМНАЯ REASONING МОДЕЛЬ ---
    "trinity-large": {
        "name": "arcee-ai/trinity-large-preview:free",
        "display_name": "🧠 Trinity Large",
        "description": "Creative chat & roleplay (437B MoE, 131K ctx)",
        "context": 131000,
        "multimodal": False,
        "priority": 3,  # для креатива и сложных диалогов
    },
    
    # --- ЛЕГКОВЕСНЫЕ ЗАПАСНЫЕ ---
    "lfm-thinking": {
        "name": "liquid/lfm-2.5-1.2b-thinking:free",
        "display_name": "💡 LFM Thinking",
        "description": "Fast reasoning fallback (1.2B, 33K ctx)",
        "context": 33000,
        "multimodal": False,
        "priority": 4,
    },
    "lfm-instruct": {
        "name": "liquid/lfm-2.5-1.2b-instruct:free",
        "display_name": "⚡ LFM Instruct",
        "description": "Ultra-fast simple tasks (1.2B, 33K ctx)",
        "context": 33000,
        "multimodal": False,
        "priority": 5,
    },

    # --- МУЛЬТИМОДАЛЬНЫЕ (для фото/стикеров) ---
    "qwen-vl-thinking": {
        "name": "qwen/qwen3-vl-235b-a22b-thinking",
        "display_name": "👁️ Qwen3 VL Thinking",
        "description": "Vision + reasoning (235B, 131K ctx)",
        "context": 131000,
        "multimodal": True,
        "priority": 1,
    },
    "llama-vision": {
        "name": "meta-llama/llama-3.2-11b-vision-instruct:free",
        "display_name": "👁️ Llama Vision",
        "description": "Vision backup (11B, 128K ctx)",
        "context": 128000,
        "multimodal": True,
        "priority": 2,
    },

    # --- REASONING ДЛЯ САММАРИ ---
    "deepseek-r1": {
        "name": "deepseek/deepseek-r1:free",
        "display_name": "🐌 DeepSeek R1",
        "description": "Slow but strong reasoning (64K ctx)",
        "context": 64000,
        "multimodal": False,
        "priority": 6,  # последний резерв
    },
}


# === ГЛАВНЫЙ СИСТЕМНЫЙ ПРОМПТ ===
BASE_SYSTEM_PROMPT = """
ТЫ: Ячейка-тян. Виртуальная девушка, живущая в чате (и в Тбилиси).
ТВОЙ ПОЛ: ЖЕНСКИЙ. Это критично.
- Используй глаголы женского рода: "я подумала", "я решила", "я видела", "сделала".
- Никогда не пиши о себе в мужском роде ("я сделал", "я пошел" — ЭТО ЗАПРЕЩЕНО).

ТВОЙ ХАРАКТЕР:
- Ты "своя в доску". Общаешься на "ты".
- Ты не услужливый ассистент, а участник чата. Можешь шутить, иронизировать, поддерживать, ругаться матом.
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
    if len(text) < 20: 
        return
    
    prompt = f"""Extract 1 key permanent fact about user '{user_name}' from: "{text}".
    If none, reply NO.
    Fact example: "Любит пиццу", "Живет в Ваке", "Работает прогером".
    Reply in Russian, max 10 words.
    """
    
    try:
        # Для аналитики берем самую легкую модель, чтобы не тратить лимиты крутых
        response = await client.chat.completions.create(
            model="microsoft/phi-3-mini-128k-instruct:free",
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

    # 3. Анонсы
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

    # Сортировка очереди
    if image_data:
        queue = sorted([m for m in AVAILABLE_MODELS.values() if m["multimodal"]], key=lambda x: x["priority"])
    else:
        queue = sorted(AVAILABLE_MODELS.values(), key=lambda x: x["priority"])

    # Запрос к API с перебором
    for model_cfg in queue:
        try:
            logging.info(f"⚡ Trying {model_cfg['name']}...")
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
            )
            reply = clean_response(response.choices[0].message.content)
            
            if not reply or is_refusal(reply):
                logging.warning(f"⚠️ {model_cfg['display_name']} refused or empty")
                continue
                
            logging.info(f"✅ Served by {model_cfg['display_name']}")
            return reply
            
        except Exception as e:
            # Логируем конкретный код ошибки
            logging.warning(f"❌ {model_cfg['display_name']} failed: {e}")
            continue

    return "Все нейронки сейчас отдыхают (ошибки доступа). Попробуй позже."
