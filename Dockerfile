FROM python:3.10-slim

# Запрещаем Python создавать файлы .pyc и включаем немедленный вывод логов
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Установка системных зависимостей (если понадобятся для Pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fly.io обычно использует 8080 по умолчанию
EXPOSE 8080

CMD ["python", "bot.py"]
