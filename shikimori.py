# services/shikimori.py

import aiohttp
import logging

async def search_anime_info(query):
    """
    Ищет аниме на Shikimori и возвращает краткую инфо.
    """
    if not query or len(query) < 3:
        return None

    url = "https://shikimori.one/api/animes"
    headers = {
        "User-Agent": "YachejkaBot (Telegram)",
        # Shikimori просит указывать User-Agent
    }
    params = {
        "search": query,
        "limit": 1,
        "order": "popularity",
        "score": 6 # Отсекаем совсем треш, если нужно
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        anime = data[0]
                        base_url = "https://shikimori.one"
                        return {
                            "title": anime.get("russian") or anime.get("name"),
                            "score": anime.get("score"),
                            "kind": anime.get("kind"),
                            "episodes": anime.get("episodes"),
                            "url": f"{base_url}{anime.get('url')}",
                            "status": anime.get("status")
                        }
    except Exception as e:
        logging.error(f"⚠️ Shikimori Error: {e}")
    
    return None
