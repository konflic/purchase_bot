FROM python:3.10

WORKDIR /bot

RUN apt update
RUN apt install git -y

COPY requirements.txt .

RUN pip install -U pip
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
