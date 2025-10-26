FROM python:3.10-slim

RUN pip install psycopg2-binary pyyaml kubernetes

COPY controller.py /app/controller.py
WORKDIR /app

CMD ["python", "controller.py"]
