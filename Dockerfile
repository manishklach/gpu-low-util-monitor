FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY pyproject.toml README.md LICENSE ./
COPY gpu_low_util_monitor ./gpu_low_util_monitor

RUN pip install --upgrade pip && \
    pip install .[nvml,prometheus]

RUN mkdir -p /var/log/gpu-low-util-monitor && chown -R appuser:appuser /app /var/log/gpu-low-util-monitor

USER appuser

ENTRYPOINT ["gpu-low-util-monitor"]
CMD ["--interval","1","--window-short","60","--window-long","1200","--out-dir","/var/log/gpu-low-util-monitor","--jsonl","--csv","--console-refresh","10"]
