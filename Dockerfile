FROM python:3.11-slim

# Runtime libs opencv needs (headless — no libgl driver stack pulled in beyond this)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# CPU-only torch/torchvision wheels — the default PyPI wheels pull in CUDA
# libraries that are useless on a Pi and add ~2GB+ to the image.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "main.py", "--stream"]
