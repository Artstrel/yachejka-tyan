# Используем легкий образ Python
FROM python:3.10-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл с зависимостями и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код
COPY . .

# Указываем права (опционально, но полезно для HF)
RUN chmod -R 777 /app

# Открываем порт 7860 (стандарт HF Spaces)
EXPOSE 8080

# Запускаем бота
CMD ["python", "bot.py"]
