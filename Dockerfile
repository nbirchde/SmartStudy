FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_THEME_BASE=light

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY src ./src

CMD ["sh", "-c", "streamlit run app/app.py --server.address=0.0.0.0 --server.port=${PORT:-8080}"]
