FROM python:3.12

WORKDIR /app

RUN apt update && apt install -y libavif-dev

RUN python -m pip install --upgrade pip setuptools wheel

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

RUN python -m pip install --upgrade Pillow -C [feature]=enable

COPY . /app

CMD ["bash", "start.sh"]
