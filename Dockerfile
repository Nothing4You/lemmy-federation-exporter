FROM python:3.15-slim-bookworm@sha256:575f8bc12ec26542e0678bc6b60e385218248019d433157ec327264a78c3a853 AS builder

RUN pip install -U pip setuptools wheel
RUN pip install pdm
# build dependencies for pycares and cffi, no 3.14 wheels
RUN apt-get update && apt-get install -y gcc libffi-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml pdm.lock README.md /project/

WORKDIR /project

RUN mkdir __pypackages__ && pdm sync --prod --no-editable --no-self

COPY src/ /project/src

RUN pdm sync --prod --no-editable


FROM python:3.15-slim-bookworm@sha256:575f8bc12ec26542e0678bc6b60e385218248019d433157ec327264a78c3a853

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
COPY --from=builder /project/__pypackages__/3.14/lib /project/pkgs
COPY --from=builder /project/__pypackages__/3.14/bin/* /bin/

USER $UID:$UID
WORKDIR /project
ENTRYPOINT ["python", "-m", "lemmy_federation_exporter"]
