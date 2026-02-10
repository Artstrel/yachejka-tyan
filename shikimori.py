import aiohttp
import logging

async def search_anime_info(query):
    """
    Ищет аниме на Shikimori и возвращает краткую информацию.
    """
    if not query or len(query) < 2:
        return None

    # Очищаем запрос от лишнего мусора, если нужно
    clean_query = query.replace('"', '').replace("'", "").strip()

    url = "https://shikimori.one/api/animes"
    headers = {
        "User-Agent": "YachejkaBot-Telegram/1.0", # Shikimori требует User-Agent
    }
    params = {
        "search": clean_query,
        "limit": 1,
        "score": 5, # Не ищем совсем треш
        "order": "popularity"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        anime = data[0]
                        base_url = "https://shikimori.one"
                        
                        # Собираем данные
                        return {
                            "title": anime.get("russian") or anime.get("name"),
                            "original_title": anime.get("name"),
                            "score": anime.get("score"),
                            "kind": anime.get("kind"),
                            "episodes": anime.get("episodes"),
                            "episodes_aired": anime.get("episodes_aired"),
                            "status": anime.get("status"),
                            "url": f"{base_url}{anime.get('url')}"
                        }
    except Exception as e:
        logging.error(f"⚠️ Ошибка Shikimori API: {e}")
    
    return None
