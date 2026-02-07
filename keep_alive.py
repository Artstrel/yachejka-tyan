from flask import Flask
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    return "I am alive!", 200

def run():
    # Render передает порт в переменную PORT. Если её нет, берем 10000 (стандарт Render)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def start_server():
    t = Thread(target=run)
    t.start()
