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
    # === ГЛАВНЫЕ VISION МОДЕЛИ ===
    
    "auto-router": {
        "name": "openrouter/free",
        "display_name": "🔄 Auto Router",
        "description": "Smart auto-selection",
        "context": 128000,
        "multimodal": True,
        "priority": 1
    },
    
    "qwen-vision-thinking": {
        "name": "qwen/qwen3-vl-235b-a22b-thinking:free",
        "display_name": "👁️ Qwen Vision Thinking",
        "description": "235B vision + reasoning",
        "context": 128000,
        "multimodal": True,
        "priority": 2
    },
    
    "llama-vision": {
        "name": "meta-llama/llama-3.2-11b-vision-instruct:free",
        "display_name": "🦙 Llama Vision",
        "description": "Fast image analysis",
        "context": 128000,
        "multimodal": True,
        "priority": 3
    },
    
    "pixtral-vision": {
        "name": "mistralai/pixtral-12b:free",
        "display_name": "🖼️ Pixtral 12B",
        "description": "Mistral vision model",
        "context": 128000,
        "multimodal": True,
        "priority": 4
    },
    
    "gemma-vision": {
        "name": "google/paligemma-3b-mix-448:free",
        "display_name": "💎 PaliGemma Vision",
        "description": "Google vision lightweight",
        "context": 8192,
        "multimodal": True,
        "priority": 5
    },
    
    "phi-vision": {
        "name": "microsoft/phi-3.5-vision-instruct:free",
        "display_name": "🔬 Phi-3.5 Vision",
        "description": "Microsoft multimodal",
        "context": 128000,
        "multimodal": True,
        "priority": 6
    },
    
    # === ТЕКСТОВЫЕ FALLBACK МОДЕЛИ ===
    
    "trinity-large": {
        "name": "arcee-ai/trinity-large-preview:free",
        "display_name": "💬 Trinity Large",
        "description": "Creative chat expert",
        "context": 128000,
        "multimodal": False,
        "priority": 7
    },
    
    "llama-3.3": {
        "name": "meta-llama/llama-3.3-70b-instruct:free",
        "display_name": "🦙 Llama 3.3",
        "description": "Reliable multilingual",
        "context": 66000,
        "multimodal": False,
        "priority": 8
    },
    
    "glm-air": {
        "name": "zhipuai/glm-4.5-air:free",
        "display_name": "⚡ GLM Air",
        "description": "Fast agent model",
        "context": 128000,
        "multimodal": False,
        "priority": 9
    },
    
    "nemotron-nano": {
        "name": "nvidia/nemotron-nano-9b-v2:free",
        "display_name": "🚀 Nemotron Nano",
        "description": "Ultra-fast responses",
        "context": 262000,
        "multimodal": False,
        "priority": 10
    }
}


# === ГЛАВНЫЙ СИСТЕМНЫЙ ПРОМПТ (ОБНОВЛЕННЫЙ) ===
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
        # Изменили формулировку, чтобы бот не думал, что обязан это упомянуть
        prompt += f"\n[ЧТО ТЫ ЗНАЕШЬ ПРО СОБЕСЕДНИКА (для контекста)]: {memory_text}"
        
    if query_type == "summary":
        prompt += "\nЗАДАЧА: Сделай краткую выжимку переписки. Кто что писал, о чем спорили. Без воды."
    elif query_type == "events":
        prompt += "\nЗАДАЧА: Проанализируй список анонсов и подскажи, куда стоит сходить."
    else:
        # Смягчили напоминание, чтобы не триггерить формальность
        prompt += "\nНАПОМИНАНИЕ: Будь живой, не душни."
        
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
        # ТОЛЬКО Vision модели для изображений, отсортированные по приоритету
        queue = sorted(
            [m for m in AVAILABLE_MODELS.values() if m["multimodal"]], 
            key=lambda x: x["priority"]
        )
        logging.info(f"🖼️ Image detected, using {len(queue)} vision models")
    else:
        # Для текста - все модели (Vision могут обрабатывать и текст)
        queue = sorted(AVAILABLE_MODELS.values(), key=lambda x: x["priority"])
    
    # Запрос к API с улучшенной обработкой ошибок
    for idx, model_cfg in enumerate(queue):
        try:
            logging.info(f"⚡ Trying {model_cfg['display_name']}...")
            
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
            )
            reply = clean_response(response.choices[0].message.content)
            
            if not reply or is_refusal(reply):
                logging.warning(f"❌ {model_cfg['display_name']} refused or empty")
                continue
            
            logging.info(f"✅ Served by {model_cfg['display_name']}")
            return reply
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Model {model_cfg['name']} failed: {e}")
            
            # Если это последняя модель в очереди - возвращаем понятную ошибку
            if idx == len(queue) - 1:
                if "429" in error_msg:
                    return "Устала немного... попробуй через минутку 😴"
                elif image_data:
                    return "Все vision-модели заняты, попробуй попозже 🖼️"
            continue

    return "Что-то я приуныла... (ошибка API)"
