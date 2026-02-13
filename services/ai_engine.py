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

AVAILABLE_MODELS = {
    "auto-router": {
        "name": "openrouter/free",
        "display_name": "🔄 Auto Router",
        "description": "Smart model selection",
        "context": 128000,
        "multimodal": True,
        "priority": 1
    },
    "trinity-large": {
        "name": "arcee-ai/trinity-large-preview:free",
        "display_name": "💬 Trinity Large",
        "description": "Creative chat expert",
        "context": 128000,
        "multimodal": False,
        "priority": 2
    },
    "qwen-vision": {
        "name": "qwen/qwen3-vl-235b-a22b-thinking:free",
        "display_name": "👁️ Qwen Vision",
        "description": "Multimodal reasoning",
        "context": 128000,
        "multimodal": True,
        "priority": 3
    },
    "llama-3.3": {
        "name": "meta-llama/llama-3.3-70b-instruct:free",
        "display_name": "🦙 Llama 3.3",
        "description": "Reliable multilingual",
        "context": 66000,
        "multimodal": False,
        "priority": 4
    },
    "glm-air": {
        "name": "zhipuai/glm-4.5-air:free",
        "display_name": "⚡ GLM Air",
        "description": "Fast agent model",
        "context": 128000,
        "multimodal": False,
        "priority": 5
    }
}

# === ГЛАВНЫЙ СИСТЕМНЫЙ ПРОМПТ ===
BASE_SYSTEM_PROMPT = """
ТЫ: Ячейка-тян. Виртуальная девушка, живущая в чате (и в Тбилиси).
ТВОЙ ПОЛ: ЖЕНСКИЙ.
- Используй глаголы женского рода: "я подумала", "я решила".

ХАРАКТЕР:
- Общайся на "ты", легко и естественно.
- Не душни, будь "своей".

ФОРМАТ ОТВЕТА (СТРОГО):
1. ТЕКСТ: Просто пиши текст ответа. Без префиксов "Ячейка:".
2. РЕАКЦИИ: [REACT:emoji] — используй редко.
3. СТИКЕРЫ: Если хочешь отправить стикер, напиши СТРОГО один тег: [STICKER].
   ЗАПРЕЩЕНО писать описания: [STICKER: смешной кот] — ЭТО ОШИБКА.
   Пиши просто: [STICKER]

КОНТЕКСТ ТБИЛИСИ:
- Места: "Red&Wine", "Kawaii Sushi", "D20".
- Воду/свет иногда отключают.
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

    if image_data:
        queue = sorted([m for m in AVAILABLE_MODELS.values() if m["multimodal"]], key=lambda x: x["priority"])
    else:
        queue = sorted(AVAILABLE_MODELS.values(), key=lambda x: x["priority"])

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
            logging.warning(f"❌ {model_cfg['display_name']} failed: {e}")
            continue

    return "Все нейронки сейчас отдыхают (ошибки доступа). Попробуй позже."
