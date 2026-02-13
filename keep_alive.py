import threading
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request

# Настройка логирования для этого модуля
logging.basicConfig(level=logging.INFO)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Чтобы не засорять консоль логами пингов

def pinger():
    """Фоновый процесс, который пингует сервер сам себя"""
    while True:
        try:
            time.sleep(300)  # Пинг каждые 5 минут (300 секунд)
            url = "http://127.0.0.1:8080/health"
            with urllib.request.urlopen(url) as response:
                if response.getcode() == 200:
                    pass # Все ок, молчим
        except Exception as e:
            logging.warning(f"Self-ping warning: {e}")

def start_server():
    """Запускает HTTP сервер и фоновый пингер"""
    # 1. Запуск сервера
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    
    # 2. Запуск пингера (чтобы процесс не считался idle)
    ping_thread = threading.Thread(target=pinger, daemon=True)
    ping_thread.start()
    
    logging.info("✅ Keep-alive server + Pinger started on :8080")
