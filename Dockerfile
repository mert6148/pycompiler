FROM rust:1-bookworm AS builder

WORKDIR /app

COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY web ./web

RUN cargo build --locked --release --bin pycompiler

FROM debian:bookworm-slim AS runtime

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/data /app/src \
    && chown -R app:app /app

WORKDIR /app

COPY --from=builder --chown=app:app /app/target/release/pycompiler /usr/local/bin/pycompiler
COPY --from=builder --chown=app:app /app/src ./src

ENV RUSTY_BIND_ADDRESS=0.0.0.0:3030 \
    RUSTY_DATA_DIR=/app/data

USER app:app

EXPOSE 3030

CMD ["pycompiler"]