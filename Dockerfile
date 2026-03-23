FROM python:3.11-slim

# ---------------------------------------------------------------------------
# Sistema: FFmpeg + fontconfig + wget
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    wget \
    ca-certificates \
    fonts-liberation \
  && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Fuentes: Bebas Neue (Estilos A y B) — Liberation Sans para Estilo C
# ---------------------------------------------------------------------------

# Bebas Neue
RUN mkdir -p /usr/share/fonts/truetype/bebas-neue \
  && wget -q --tries=3 \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf" \
    -O /usr/share/fonts/truetype/bebas-neue/BebasNeue-Regular.ttf

# Registrar fuentes
RUN fc-cache -fv

# ---------------------------------------------------------------------------
# Aplicación Python
# ---------------------------------------------------------------------------
WORKDIR /opt/pipeline

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generate_ass.py .
COPY worker_api.py .

EXPOSE 5001
CMD ["python", "worker_api.py"]
