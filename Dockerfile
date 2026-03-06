FROM python:3.11-slim

WORKDIR /app

# rasterio wheels include GDAL, no system deps needed
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5001

CMD ["gunicorn", "webapp.server:app", "--bind", "0.0.0.0:5001", "--timeout", "300", "--workers", "2", "--threads", "4"]
