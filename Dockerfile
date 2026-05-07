# Minimal production-shaped image (adjust workers/bind for your platform).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV HYPATIA_ENV=production

RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5001
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5001", "wsgi:application"]
