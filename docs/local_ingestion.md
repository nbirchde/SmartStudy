# Local ingestion smoke test

This is the first code path we want to prove before deploying a Cloud Function.

Goal:

```text
one PDF -> text chunks -> Vertex AI embeddings -> MongoDB Atlas
```

## Setup

Create a local `.env` file from `.env.example` and fill in the real values. `MONGODB_URI` is secret and must not be committed.

Cloud Shell is the easiest place to run this first because it already has `gcloud` authenticated for the project. Clone or pull the repo there, then install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Authenticate to Google Cloud:

```bash
gcloud auth application-default login
gcloud config set project smartstudy-h505
```

If the script cannot connect to MongoDB, check Atlas network access. The IP address of the machine running the script must be allowed. For Cloud Shell, use:

```bash
curl -s ifconfig.me
```

Add that IP in Atlas under `Database & Network Access`. Avoid `0.0.0.0/0` unless we deliberately decide to use it as a temporary demo shortcut.

## Run

Use one small lecture PDF first:

```bash
python scripts/ingest_pdf.py path/to/lecture.pdf
```

Expected result:

- the script prints the number of chunks ingested;
- Atlas Data Explorer shows documents in `smartstudy.lecture_chunks`;
- each document has `text`, `source_file`, `page`, `chunk`, and `embedding`.

If this works locally, the Cloud Function version is mostly the same logic triggered by a bucket upload.
