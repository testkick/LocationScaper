FROM mcr.microsoft.com/playwright/python:v1.53.0-jammy

WORKDIR /app

COPY . /app

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "location_scraper_webapp:app"]
