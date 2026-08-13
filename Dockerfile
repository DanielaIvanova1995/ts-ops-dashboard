# TradeHub — container image for an always-on host (Render / Railway / Fly.io).
# The app already reads every secret from environment variables first (see
# data_sources.get_secret), so nothing here needs the secrets baked in — you set
# them in the host's dashboard. Nothing about the app changes; this just lets it
# run somewhere with dedicated memory that never sleeps.
FROM python:3.11-slim

WORKDIR /app

# Install Python deps first (better layer caching). pandas/openpyxl/fpdf2 all ship
# manylinux wheels for 3.11, so no compilers are needed on slim.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# The host injects $PORT; default to 8501 for local `docker run`.
ENV PORT=8501
EXPOSE 8501

# Shell form so ${PORT} expands at runtime. Bind 0.0.0.0 + headless for a server.
CMD streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=true
