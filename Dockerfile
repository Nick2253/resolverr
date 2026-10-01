FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY resolverr/ resolverr/

ENV PYTHONUNBUFFERED=1

EXPOSE 8787

CMD ["gunicorn", "-b", "0.0.0.0:8787", "-w", "1", "--threads", "2", "resolverr.app:create_app()"]
