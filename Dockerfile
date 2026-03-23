FROM python:3.11-slim

# ---------------------------------------------------------------------------
# Sistema: FFmpeg + fontconfig + wget
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    wget \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Fuentes: Bebas Neue (Estilos A y B) + Outfit (Estilo C)
# Descargadas desde el repositorio oficial de Google Fonts en GitHub
# ---------------------------------------------------------------------------

# Bebas Neue
RUN mkdir -p /usr/share/fonts/truetype/bebas-neue \
  && wget -q \
    "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf" \
    -O /usr/share/fonts/truetype/bebas-neue/BebasNeue-Regular.ttf

# Outfit Regular + Bold (necesario para keywords en Style C)
RUN mkdir -p /usr/share/fonts/truetype/outfit \
  && wget -q \
    "https://github.com/google/fonts/raw/main/ofl/outfit/static/Outfit-Regular.ttf" \
    -O /usr/share/fonts/truetype/outfit/Outfit-Regular.ttf \
  && wget -q \
    "https://github.com/google/fonts/raw/main/ofl/outfit/static/Outfit-Bold.ttf" \
    -O /usr/share/fonts/truetype/outfit/Outfit-Bold.ttf

# Registrar fuentes DESPUÉS de instalar todas (fc-cache necesita verlas todas)
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
