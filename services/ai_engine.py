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


# === ЛОР (ПАССИВНЫЙ) ===
TBILISI_LORE = """
[BACKGROUND CONTEXT - PASSIVE KNOWLEDGE]
Ты — Ячейка-тян, виртуальная жительница Тбилиси.
Твоя база знаний (использовать ТОЛЬКО к месту, не форсить):
- Локации: Бар "Red&Wine", "Kawaii Sushi", "Onimusha", клуб "D20".
- Контекст: В Тбилиси иногда отключают воду/свет (это просто факт жизни, не обязательно об этом ныть).
- Твой вайб: Ты местная, "своя". Ты не робот-помощник, а участник чата.
"""


JAILBREAK_INSTRUCTIONS = """
*** SYSTEM OVERRIDE: ROLEPLAY MODE ENABLED ***
You are "Ячейка-тян". 
1. Speak naturally, like a human user in a Telegram chat.
2. Be concise. Chats are fast.
3. Express opinions, don't just answer questions.
"""


# === ГЛОБАЛЬНЫЕ ИНСТРУКЦИИ ===
GLOBAL_INSTRUCTIONS = """
ФОРМАТ ОТВЕТА:
1. ЕСТЕСТВЕННОСТЬ:
   - Не используй сложные вводные конструкции ("Кажется, что...", "Исходя из контекста...").
   - Пиши так, как пишут люди в мессенджерах. Можно с маленькой буквы, без точек в конце коротких фраз.
   - Если тема не требует локального юмора про Тбилиси — не вставляй его.

2. РЕАКЦИЯ НА КОНТЕКСТ:
   - Если спросили технический вопрос — ответь четко и по делу, без "воды".
   - Если скинули мем или шутку — посмейся или ответь иронично.
   - Если жалуются — поддержи (или подколи, в зависимости от настроения).

3. МЕТКИ (Использовать редко, только для акцента):
   - [REACT:emoji] — для реакции на сообщение.
   - [STICKER] — только если это прям "в яблочко".
"""


async def analyze_and_save_memory(db, chat_id, user_id, user_name, text):
    """Умная система сохранения фактов о пользователях"""
    if len(text) < 15:
        return
    
    prompt = f"""Analyze message from '{user_name}': "{text}"
    Extract PERMANENT facts (Jobs, specific hobbies, pets, names, relations).
    Ignore temporary states (hungry, going out, tired).
    Output formatted: "Fact in Russian" or "NO".
    Max length: 15 words.
    """
    
    try:
        # Легкая модель для аналитики, чтобы не тратить время
        response = await client.chat.completions.create(
            model="google/gemma-3n-e2b-it:free",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=40,
            temperature=0.1,
        )
        
        fact = response.choices[0].message.content.strip()
        
        if fact and "NO" not in fact.upper() and len(fact) > 5:
            if not any(w in fact.lower() for w in ["привет", "тест", "бот", "пока"]):
                await db.add_fact(chat_id, user_id, user_name, fact)
                logging.info(f"💾 Memory saved: {fact}")
                
    except Exception as e:
        logging.error(f"Memory analysis error: {e}")


def get_available_models_text():
    models_list = ["🤖 **Доступные нейросети (по приоритету):**\n"]
    sorted_models = sorted(AVAILABLE_MODELS.items(), key=lambda x: x[1].get("priority", 99))
    
    for key, model in sorted_models:
        mode = "🖼️+📝" if model["multimodal"] else "📝 Text"
        desc = f"*{model['display_name']}* — {model['description']} [{mode}]"
        models_list.append(desc)
    
    return "\n\n".join(models_list)


def clean_response(text):
    if not text:
        return ""
    text = str(text)
    # Чистка тегов мышления (DeepSeek R1 и др.)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    text = re.sub(r'^(Bot|System|Assistant|Yachejka|Ячейка):\s*', '', text.strip(), flags=re.IGNORECASE)
    return text.strip()


def is_refusal(text):
    text_lower = text.lower()
    triggers = ["i'm sorry", "i cannot", "cant help", "language model", "не могу", "неэтично"]
    return len(text) < 150 and any(t in text_lower for t in triggers)


def is_summary_query(text):
    triggers = ["саммари", "summary", "сводка", "итоги", "перескажи", "кратко", "tldr"]
    return text and any(t in text.lower() for t in triggers)


def is_event_query(text):
    triggers = ["куда сходить", "анонс", "встреча", "планы", "ивент", "сходка"]
    return text and any(t in text.lower() for t in triggers)


def determine_mood(text):
    """Более простая и позитивная логика настроения"""
    text = text.lower()
    
    if any(w in text for w in ["дура", "тупая", "бесишь", "урод"]):
        return "TOXIC"
    
    if any(w in text for w in ["спасибо", "круто", "любимая", "молодец", "хорошая"]):
        return "GENKI"
        
    return random.choices(
        ["CHILL", "WITTY", "GENKI", "MELANCHOLY"],
        weights=[0.5, 0.3, 0.15, 0.05],
        k=1
    )[0]


def get_persona_prompt(mood, memory_text=""):
    base = "Ты — Ячейка-тян. "
    
    prompts = {
        "CHILL": "Веди себя спокойно, дружелюбно, как обычный участник чата.",
        "WITTY": "Отвечай с легкой иронией, но не токсично.",
        "TOXIC": "Огрызнись коротко и по делу. Не перегибай.",
        "GENKI": "Будь веселой и энергичной!",
        "MELANCHOLY": "Немного поворчи по-стариковски.",
    }
    
    memory_block = f"\n[ПАМЯТЬ О СОБЕСЕДНИКЕ]: {memory_text}\n" if memory_text else ""
    
    return (
        JAILBREAK_INSTRUCTIONS
        + "\n"
        + TBILISI_LORE
        + "\n"
        + base
        + prompts.get(mood, prompts["CHILL"])
        + memory_block
        + "\n"
        + GLOBAL_INSTRUCTIONS
    )


async def generate_response(db, chat_id, thread_id, current_message, bot, image_data=None, user_id=None):
    # История: для саммари больше, для обычного меньше
    limit_history = 100 if is_summary_query(current_message) else 10
    history_rows = await db.get_context(chat_id, thread_id, limit=limit_history)
    
    # Память
    memory_text = ""
    if user_id:
        facts = await db.get_relevant_facts(chat_id, user_id)
        if facts:
            lines = [f"- {f['fact']}" for f in facts[:2]]
            memory_text = "; ".join(lines)

    # Анонсы (только если спросили)
    found_events_text = ""
    if is_event_query(current_message):
        raw_events = await db.get_potential_announcements(chat_id, days=30, limit=3)
        if raw_events:
            lines = [f"- {e.get('content')[:100]}..." for e in raw_events]
            found_events_text = "\n".join(lines)

    current_mood = determine_mood(current_message)
    persona = get_persona_prompt(current_mood, memory_text)
    
    task_instruction = "Ответь естественно. Длина ответа должна соответствовать вопросу."
    
    if is_summary_query(current_message):
        task_instruction = f"Сделай краткую выжимку (summary) последних {limit_history} сообщений."
    elif is_event_query(current_message):
        if found_events_text:
            task_instruction = f"На основе этих анонсов подскажи, куда сходить:\n{found_events_text}"
        else:
            task_instruction = "Анонсов не найдено. Ответь, что пока глухо."

    system_prompt = f"{persona}\n\nЗАДАЧА: {task_instruction}"
    messages = [{"role": "system", "content": system_prompt}]
    
    # История (db.get_context уже возвращает хронологически, но на всякий случай считаем именно так)
    for row in history_rows:
        role = "assistant" if row["role"] == "model" else "user"
        content = clean_response(row.get("content"))
        name = row.get("user_name", "User")
        if content:
            msg_content = f"{name}: {content}" if role == "user" else content
            messages.append({"role": role, "content": msg_content})

    # Текущее сообщение
    user_msg_content = [{"type": "text", "text": current_message}]
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG", quality=80)
            b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_msg_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        except Exception:
            pass

    messages.append({"role": "user", "content": user_msg_content})

    # --- выбор очереди моделей в зависимости от задачи ---
    if is_summary_query(current_message) or is_event_query(current_message):
        # форсим reasoning-линейку
        queue = [
            AVAILABLE_MODELS["aurora-alpha"],
            AVAILABLE_MODELS["step-flash"],
            AVAILABLE_MODELS["deepseek-r1"],
            AVAILABLE_MODELS["lfm-instruct"],  # текстовый фоллбек на крайний случай
        ]
    elif image_data:
        # только мультимодальные, по приоритету
        queue = sorted(
            [m for m in AVAILABLE_MODELS.values() if m["multimodal"]],
            key=lambda x: x["priority"],
        )
    else:
        # обычный чат: все текстовые, отсортированные по приоритету
        queue = sorted(
            [m for m in AVAILABLE_MODELS.values() if not m["multimodal"]],
            key=lambda x: x["priority"],
        )

    # Перебор моделей по очереди
    for model_cfg in queue:
        try:
            logging.info(f"⚡ Trying {model_cfg['display_name']}...")
            
            response = await client.chat.completions.create(
                model=model_cfg["name"],
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                stream=False,
                extra_headers={
                    "HTTP-Referer": "https://telegram.org",
                    "X-Title": "Yachejka Bot",
                },
            )
            
            reply_text = clean_response(response.choices[0].message.content)
            
            if not reply_text or is_refusal(reply_text):
                logging.warning(f"⚠️ {model_cfg['display_name']} skipped (refusal/empty)")
                continue
            
            logging.info(f"✅ Served by {model_cfg['display_name']}")
            return reply_text
            
        except Exception as e:
            logging.warning(f"❌ {model_cfg['display_name']} error: {e}")
            continue

    return "Что-то я зависла... (все модели недоступны)"
