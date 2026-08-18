FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Forme "shell" (pas de crochets) volontairement, pour que ${FRONTEND_PORT}
# soit bien substitué par le shell au démarrage du container.
CMD streamlit run app.py --server.address=0.0.0.0 --server.port=${FRONTEND_PORT:-8501}
