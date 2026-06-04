FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create directories for reports and persistent config
RUN mkdir -p reports /data

# /data is the Amvera persistent volume
VOLUME ["/data"]

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8000", "--timeout", "120", "--graceful-timeout", "30", "app:app"]
