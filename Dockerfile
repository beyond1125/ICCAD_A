FROM python:3.11-slim AS abc-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ gcc make git \
    && rm -rf /var/lib/apt/lists/*

# Berkeley ABC: required at runtime for reduce_depth and check_equivalence.
RUN git clone --depth 1 https://github.com/berkeley-abc/abc.git /abc \
    && make -C /abc -j"$(nproc)" ABC_USE_NO_READLINE=1 abc


FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python scripts/build_parser.py

# Placed after COPY so the freshly built binary wins over any host leftover.
COPY --from=abc-builder /abc/abc /app/tools/abc/abc

CMD ["./cada1066_alpha", "-config", "config.yaml"]
