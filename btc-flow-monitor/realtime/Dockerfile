FROM python:3.12-slim
WORKDIR /app
COPY btc-flow-monitor/realtime/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY btc-flow-monitor /app/btc-flow-monitor
RUN useradd --uid 10001 --create-home paper && mkdir /state && chown paper:paper /state
USER paper
ENV PAPER_ONLY=true REAL_TRADING=false PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "btc-flow-monitor/realtime_runtime.py", "--state-dir", "/state", "--host", "0.0.0.0"]
