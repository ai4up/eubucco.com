FROM python:3.9-slim-bullseye

WORKDIR /app

COPY ./requirements /app/requirements
#RUN pip install --no-cache-dir --upgrade -r /app/requirements/local.txt
RUN pip install --upgrade -r /app/requirements/local.txt

# gdal proj install
RUN apt-get update \
    && apt-get -y install netcat gcc postgresql \
    && apt-get clean

RUN apt-get update \
    && apt-get install -y binutils libproj-dev gdal-bin python3-gdal proj-bin


COPY ./config /app/config
COPY ./eubucco /app/eubucco
COPY ./theme /app/theme

CMD ["uvicorn", "eubucco.api.main:api", "--host", "0.0.0.0", "--port", "8001"]
