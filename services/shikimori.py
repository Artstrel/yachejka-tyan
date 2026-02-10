import aiohttp
import logging

async def search_anime_info(query):
    """
    Ищет аниме на Shikimori API v1.
    """
    if not query or len(query) < 2:
        return None

    # Очистка названия от мусора (кавычки и т.д.)
    clean_query = query.replace('"', '').replace("'", "").strip()
    
    # URL для поиска
    url = "https://shikimori.one/api/animes"
    
    # Обязательно нужен User-Agent, иначе Shikimori может заблочить (403 Forbidden)
    headers = {
        "User-Agent": "YachejkaBot-Telegram/1.0 (helper bot)", 
    }
    
    params = {
        "search": clean_query,
        "limit": 1,
        "order": "popularity", # Сортируем по популярности, чтобы найти самое известное
        "score": 4             # Отсекаем треш с рейтингом ниже 4
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        anime = data[0]
                        base_url = "https://shikimori.one"
                        
                        # Собираем красивый объект ответа
                        return {
                            "title": anime.get("russian") or anime.get("name"),
                            "original_title": anime.get("name"),
                            "score": anime.get("score"),
                            "kind": anime.get("kind"),
                            "status": anime.get("status"),
                            "episodes": anime.get("episodes"),
                            "episodes_aired": anime.get("episodes_aired"),
                            "url": f"{base_url}{anime.get('url')}",
                            "poster": f"{base_url}{anime.get('image', {}).get('original')}"
                        }
                else:
                    logging.warning(f"⚠️ Shikimori вернул статус: {resp.status}")
    except Exception as e:
        logging.error(f"❌ Ошибка при запросе к Shikimori: {e}")
    
    return None
