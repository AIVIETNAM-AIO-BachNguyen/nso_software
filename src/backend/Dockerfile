FROM python:3.12.16-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 NSO_ENV=production
WORKDIR /app
COPY requirements-research.lock.txt .
RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-research.lock.txt
COPY api.py report.py nso_core.py nso_v2.py research*.py ./
COPY nso ./nso
COPY scripts ./scripts
COPY migrations ./migrations
RUN useradd --create-home --uid 10001 nso
USER nso
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
