FROM python:3.12-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements-web.txt ./
COPY badminton_reservation/requirements.txt badminton_reservation/requirements.txt
RUN pip install --no-cache-dir -r requirements-web.txt playwright==1.63.0 \
    && python -m playwright install --with-deps --no-shell chromium \
    && apt-get update && apt-get install -y --no-install-recommends xvfb xauth fonts-wqy-zenhei gosu tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 quest \
    && mkdir -p /data && chown quest:quest /data
COPY badminton_reservation badminton_reservation
COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod 755 /app/entrypoint.sh
USER quest
EXPOSE 18880
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/app/entrypoint.sh"]
