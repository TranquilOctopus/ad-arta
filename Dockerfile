FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
# Mount a folder holding config.toml, tv-token.txt and .pyatv.conf at /data
WORKDIR /data
ENV HOME=/data
ENTRYPOINT ["ad-arta", "--config", "/data/config.toml"]
CMD ["run"]
