FROM python:3.13-slim-bookworm@sha256:56a11364ffe0fee3bd60af6d6d5209eba8a99c2c16dc4c7c5861dc06261503cc AS builder

RUN pip install -U pip setuptools wheel
RUN pip install pdm
# build dependencies for pycares, no 3.13 wheel
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml pdm.lock README.md /project/

WORKDIR /project

RUN mkdir __pypackages__ && pdm sync --prod --no-editable --no-self

COPY src/ /project/src

RUN pdm sync --prod --no-editable


FROM python:3.13-slim-bookworm@sha256:56a11364ffe0fee3bd60af6d6d5209eba8a99c2c16dc4c7c5861dc06261503cc

ARG UID=34130

# ensure no buffers, prevents losing logs e.g. from crashes
ENV PYTHONUNBUFFERED=1
# ensure we see tracebacks in C crashes
ENV PYTHONFAULTHANDLER=1

RUN addgroup --gid "$UID" containeruser && \
  adduser --uid "$UID" --ingroup containeruser --disabled-login --home /home/containeruser --shell /bin/false containeruser && \
  mkdir /project && \
  chown $UID:$UID /project

ENV PYTHONPATH=/project/pkgs
COPY --from=builder /project/__pypackages__/3.13/lib /project/pkgs
COPY --from=builder /project/__pypackages__/3.13/bin/* /bin/

USER $UID:$UID
WORKDIR /project
ENTRYPOINT ["python", "-m", "lemmy_federation_exporter"]
