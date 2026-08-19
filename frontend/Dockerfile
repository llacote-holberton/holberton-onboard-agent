FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Shell form on purpose (no brackets), so ${FRONTEND_PORT} actually gets
# substituted by the shell when the container starts.
CMD streamlit run app.py --server.address=0.0.0.0 --server.port=${FRONTEND_PORT:-8501}
