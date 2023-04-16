FROM python:3.10

WORKDIR /srv
COPY ./requirements.txt .

RUN python3 -m venv venv && . venv/bin/activate
RUN python3 -m pip install --no-cache-dir -r requirements.txt --upgrade pip

COPY ./app.py /srv/app.py
COPY ./db.py /srv/db.py
COPY ./static /srv/static
COPY ./templates /srv/templates
COPY ./config.py /srv/config.py
COPY ./gpt4all_grpc.py /srv/gpt4all_grpc.py
COPY ./protos /srv/protos

# COPY ./models /srv/models  # Mounting model is more efficient
# CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "9600", "--db_path", "data/database.db"]
CMD ["python", "gpt4all_grpc.py", "--db_path", "data/database.db"]