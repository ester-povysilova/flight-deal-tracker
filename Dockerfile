FROM python:3.12-slim

WORKDIR /app

# Install cron
RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Setup cron to run every 6 hours
RUN echo "0 */6 * * * cd /app && python -m src.tracker >> /var/log/flight_tracker.log 2>&1" > /etc/cron.d/flight-tracker \
    && chmod 0644 /etc/cron.d/flight-tracker \
    && crontab /etc/cron.d/flight-tracker

# Default entrypoint runs once immediately, then starts cron daemon
CMD ["sh", "-c", "python -m src.tracker && cron -f"]
