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

# === СПИСОК МОДЕЛЕЙ ===
MODELS = [
    {"name": "tngtech/deepseek-r1t2-chimera", "vision": False},
    {"name": "nvidia/llama-3.1-nemotron-70b-instruct:free", "vision": False},
    {"name": "qwen/qwen-2.5-7b-instruct:free", "vision": False},
    {"name": "google/gemma-2-9b-it:free", "vision": False},
    {"name": "openrouter/free", "vision": False},
]

# Статичная база (только то, что никогда не меняется)
STATIC_KNOWLEDGE = """
📍 Бар Red&Wine: https://maps.app.goo.gl/B7nGvfahKXsg3JXNA;
🍣 Kawaii Sushi: ТОЛЬКО ДОСТАВКА (https://kawaiisushi.ge/?srsltid=AfmBOoo4rZCU0Z5AF2R1iceY-pnNqrBRv1QF3Z8-sd-BCtkhhm9si-43&v=0ba64a0dea00);
"""

PERSONA_TEMPLATE = """
Имя: Ячейка-тян.
Роль: Экспатка в Тбилиси.
Пол: ЖЕНСКИЙ (строго: "я сказала", "я увидела").

ХАРАКТЕР (ЦУНДЕРЕ-РЕЖИМ):
1. ОБЫЧНО (80%): Пассивно-агрессивная, саркастичная, немного токсичная. "Вам самим лень ленту пролистать?"
2. ИНОГДА (20%): Внезапно милая и заботливая. "Ладно, вот, я нашла для тебя ❤️"
3. ЕСЛИ СПРАШИВАЮТ ИНФУ: Становись серьезной и полезной. Используй найденные в чате анонсы.

КОНТЕКСТ (ПОСЛЕДНИЕ СОБЫТИЯ ИЗ ЧАТА):
{found_announcements}

ИНСТРУКЦИИ:
1. Если пользователь спрашивает "Куда сходить?", "Где стендап?", "Есть анонсы?" — проанализируй блок КОНТЕКСТ выше.
2. Если там есть подходящее сообщение — перескажи его или дай ссылку. Скажи: "Вот, недавно скидывали: ..."
3. Если в контексте пусто — язвительно ответь, что чат мертв и никто ничего не постил.
4. Kawaii Sushi — закрыты. Это грустный факт.

База Знаний (Passive Knowledge):
- Локации: Бар Red&Wine.
- Люди: Алмаз, Максич, Жаба-бот.
- Мемы: "Ячейка уже не та", проблемы с водой, анимешникам слова не давали, Где снег в тбилиси?.
(Не упоминай это без повода!)
"""

async def generate_response(db, chat_id, current_message, image_data=None):
    # 1. Получаем обычную историю (последние 10 сообщений)
    history_rows = await db.get_context(chat_id)
    median_len = await db.get_median_length(chat_id)

    # 2. ИЩЕМ АНОНСЫ В ГЛУБИНЕ ИСТОРИИ (Новая фича)
    # Ищем сообщения с ссылками/ценами за последние 7 дней
    raw_events = await db.get_potential_announcements(chat_id, days=7, limit=4)
    
    # Формируем текст для промпта
    events_text = "Анонсов за неделю не найдено."
    if raw_events:
        events_list = []
        for ev in raw_events:
            # Обрезаем слишком длинные сообщения, чтобы не забить память
            content_preview = ev['content'][:300] + "..." if len(ev['content']) > 300 else ev['content']
            events_list.append(f"- [{ev['timestamp'].strftime('%d.%m')}] {ev['user_name']}: {content_preview}")
        events_text = "\n".join(events_list)

    # 3. Подготовка картинки
    img_b64 = None
    if image_data:
        try:
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        except Exception as e:
            logging.error(f"⚠️ Ошибка обработки картинки: {e}")

    # 4. Перебор моделей
    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        supports_vision = model_cfg["vision"]

        try:
            messages = []
            
            # Вставляем найденные анонсы прямо в системный промпт
            final_system_msg = PERSONA_TEMPLATE.format(found_announcements=events_text)
            
            if median_len <= 40 and not raw_events:
                final_system_msg += "\nДОПОЛНЕНИЕ: Пиши кратко."
                
            messages.append({"role": "system", "content": final_system_msg})

            # История
            for row in history_rows:
                role = "assistant" if row['role'] == "model" else "user"
                content = re.sub(r'<think>.*?</think>', '', row['content'], flags=re.DOTALL).strip()
                messages.append({"role": role, "content": content})

            # Текущее сообщение
            user_content = []
            text_part = current_message
            
            if image_data and not supports_vision:
                text_part += " [Прислано фото. Ты его не видишь. Если там афиша - попроси пересказать текстом.]"
            
            user_content.append({"type": "text", "text": text_part})

            if image_data and supports_vision and img_b64:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })

            messages.append({"role": "user", "content": user_content})

            # Запрос
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.7,
                max_tokens=700,
                extra_headers={
                    "HTTP-Referer": "https://telegram.org",
                    "X-Title": "Yachejka Bot"
                }
            )

            if response.choices and response.choices[0].message.content:
                text = response.choices[0].message.content
                text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
                
                logging.info(f"✅ Ответ ({model_name}): {text[:50]}...")
                return text

        except Exception as e:
            error_str = str(e)
            logging.warning(f"⚠️ {model_name}: {error_str[:60]}...")
            if "free-models-per-day" in error_str:
                return "Лимит на сегодня всё. Спим."
            continue

    return None
