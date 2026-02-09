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
    
    # Ищем анонсы
    raw_events = await db.get_potential_announcements(chat_id, days=14, limit=3)

    found_events_text = ""
    has_relevant_info = False
    
    if raw_events:
        events_list = []
        for ev in raw_events:
            # === ИСПРАВЛЕНИЕ ===
            # Больше не обрезаем текст! Передаем контент целиком, чтобы бот увидел "подвал" сообщения.
            content = ev['content'] 
            
            date_str = ev.get('timestamp').strftime('%d.%m')
            user_name = ev['user_name']
            
            # Формируем четкий блок для нейросети
            events_list.append(f"--- АНОНС ОТ {user_name} ({date_str}) ---\n{content}\n---------------------------")
        
        found_events_text = "⚠️ В БАЗЕ НАЙДЕНЫ СЛЕДУЮЩИЕ АНОНСЫ:\n" + "\n".join(events_list)
        has_relevant_info = True

    # === ЛОГИКА ВЫБОРА ПРОМПТА ===
    
    if has_relevant_info:
        # РЕЖИМ: АНАЛИЗАТОР (ОБНОВЛЕННЫЙ)
        SYSTEM_PROMPT = f"""
Ты — Ячейка-тян.
Твоя задача — извлечь факты из текста анонсов и ответить пользователю.

{found_events_text}

ИНСТРУКЦИЯ ПО АНАЛИЗУ:
1. Внимательно прочитай тексты анонсов выше (от начала до самого конца).
2. Обычно важная инфо (Где/Когда) находится В КОНЦЕ сообщения, после описания.
3. Ищи маркеры: "Место", "Собираемся", "Начало", "Вход", значки 🪧, 🚸, 📍.
4. Ищи дату в заголовке или тексте (например "31.01", "Суббота").

ЗАДАЧА:
Если пользователь спрашивает "Куда сходить?" или про конкретное событие:
- Кратко скажи: "Есть анонс на [Название]!"
- Напиши: "📅 Когда: [Дата и Время]"
- Напиши: "📍 Где: [Место/Адрес]" (Если есть ссылка на карту/чат в тексте — вставь её).
- Напиши: "💰 Вход: [Условия]"
- Добавь пару слов про само событие (из описания).

СТИЛЬ:
Полезный, но в твоем духе (можешь добавить легкий комментарий, если аниме странное).
"""
    else:
        # РЕЖИМ: ПУСТО
        SYSTEM_PROMPT = """
Ты — Ячейка-тян, циничная экспатка.
Контекст: Я просканировала чат, но не нашла свежих анонсов (или не поняла их).

Если спрашивают "Куда сходить?":
- Скажи: "В базе анонсов пусто. Либо никто ничего не постит, либо я ослепла."
- Предложи пойти в бар Red&Wine или поплакать о Kawaii Sushi.

Стиль: Саркастичный, краткий.
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
        except Exception as e:
            logging.error(f"Image error: {e}")

    messages.append({"role": "user", "content": user_content})

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.5,
                max_tokens=1000, # Увеличили лимит ответа, так как входных данных стало больше
                extra_headers={"HTTP-Referer": "https://telegram.org", "X-Title": "Yachejka Bot"}
            )

            if response.choices and response.choices[0].message.content:
                final_text = clean_response(response.choices[0].message.content)
                if not final_text: continue
                return final_text

        except Exception as e:
            if "free-models-per-day" in str(e): return "Лимит исчерпан."
            continue

    return None
