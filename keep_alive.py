from aiohttp import web

async def handle(request):
    return web.Response(text="I am alive! Bot is running.")

async def start_server():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    # Koyeb ищет порт 8000 по умолчанию
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
