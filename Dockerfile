FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Der heruntergeladene Vorrat bleibt zwischen zwei Bauten liegen. Greift die
# Schicht aus dem Cache, kostet das hier nichts; greift sie nicht — weil
# BuildKit bei knapper Platte aufgeraeumt hat —, installiert pip aus dem
# Vorrat statt aus dem Netz. Am 12.09.2026 dauerte dieser Schritt deshalb
# 18,9 Sekunden, obwohl sich an requirements.txt seit Wochen nichts geaendert
# hatte. `--no-cache-dir` waere nur dann richtig, wenn das Abbild kleiner
# werden soll — der Vorrat liegt hier aber ausserhalb des Abbilds.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Version und Änderungsliste gehören ins Abbild: Die Oberfläche zeigt beides
# an, und ohne sie stünde dort nur eine Commit-Kennung.
COPY VERSION CHANGELOG.md ./
COPY app ./app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
