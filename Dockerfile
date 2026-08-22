FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
RUN mkdir -p data/generated data/evaluation models
RUN python scripts/generate_data.py && python scripts/train_tlearner.py && python scripts/evaluate_final.py
EXPOSE 8000
CMD ["gunicorn","app.main:app","-k","uvicorn.workers.UvicornWorker","-b","0.0.0.0:8000"]
