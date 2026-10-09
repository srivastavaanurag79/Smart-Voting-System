FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=False \
    AADHAAR_PROVIDER=mock \
    ELECTION_KEY_DIR=/data/keys

WORKDIR /app

# OpenCV needs a couple of system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn whitenoise

COPY . .

RUN mkdir -p /data/keys ml/recognizer

EXPOSE 8000

# Migrate, seed demo data, then serve.
CMD ["sh", "-c", "python manage.py migrate && python manage.py seed_demo && gunicorn HCI.wsgi --bind 0.0.0.0:8000 --workers 2 --timeout 120"]