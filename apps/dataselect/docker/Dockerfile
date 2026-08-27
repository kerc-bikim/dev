FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential make ca-certificates libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN make

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libcurl4 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/dataselect /usr/local/bin/dataselect
ENTRYPOINT ["dataselect"]
