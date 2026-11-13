FROM python:3.12-slim
WORKDIR /code
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# /code는 root 소유라 appuser가 쓸 수 없음 → pytest 캐시(.pytest_cache)를 만들지 않게 한다.
ENV PYTEST_ADDOPTS="-p no:cacheprovider"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 10001 --create-home appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser frontend ./frontend
COPY --chown=appuser:appuser tests ./tests
COPY --chown=appuser:appuser seed.py .
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
