# SmartStudy Cloud Agent

SmartStudy is our INFO-H505 cloud project. A student creates a folder, uploads lecture PDFs, the system indexes the content, and a small tutor app answers questions using only the notes from that folder.

The app is already deployed here:

```text
https://smartstudy-app-376906403882.europe-west1.run.app
```

## What it does

1. The student creates or opens a folder in the Streamlit app.
2. The student uploads lecture PDFs into that folder.
3. The app stores each PDF in Google Cloud Storage under a folder-scoped path.
4. A Cloud Function runs automatically when the PDF arrives in the bucket.
5. The function extracts text, splits it into chunks, creates Vertex AI embeddings, and stores the chunks in MongoDB Atlas Vector Search with the folder metadata.
6. The app stores workspace chat threads in MongoDB and keeps each chat's history separate.
7. The tutor retrieves the closest chunks from the active folder only and sends the retrieved context plus the active chat history to Gemini 2.5 Flash.
8. Gemini answers as a formal academic tutor and cites the source file/page when the context supports it.

## Main folders

```text
smartstudy/
  app/                    Streamlit app
  cloud_function/         GCS-triggered ingestion function
  docs/                   Architecture notes and report material
  scripts/                Local/deploy helper scripts
  src/smartstudy/         Shared retrieval and tutor code
```

## Cloud resources

```text
GCP project:       smartstudy-h505
Region:            europe-west1
PDF bucket:        gs://smartstudy-h505-pdfs/
Cloud Function:    ingest-pdf
Cloud Run app:     smartstudy-app
MongoDB database:  smartstudy
MongoDB collection: lecture_chunks
Chat collection:     workspace_chats
Vector index:      lecture_vector_index
Static egress IP:  104.155.37.123
Retention:         7 days for folder PDFs and indexed chunks
```

The deployed app and function both read `MONGODB_URI` from Google Secret Manager. Their outbound MongoDB traffic goes through the VPC connector and Cloud NAT, so Atlas only needs to allow the static GCP egress IP.

Uploads are stored under `folders/{folder_id}/...`. The `folder_id` and `folder_path` are included in each MongoDB chunk and used as Atlas Vector Search filters, so the tutor retrieves notes from the active folder only. Chat threads are stored in `workspace_chats` with the same folder scope. This is folder compartmentalization, not login-based access control: anyone with a folder URL can use that folder workspace and see its chats.

## Local setup

Local setup is still useful for development, but the demo should use the Cloud Run URL above.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with the real values. Do not commit it.

Run the app locally:

```bash
streamlit run app/app.py
```

If you run locally, MongoDB Atlas must allow your current IP address. The hosted Cloud Run app does not need that personal IP entry because it uses the static GCP egress IP.

## Deploying the app

Redeploy the Cloud Function first so new folder uploads are indexed with folder metadata:

```bash
GOOGLE_CLOUD_PROJECT=smartstudy-h505 \
GCS_BUCKET_NAME=smartstudy-h505-pdfs \
./scripts/deploy_function.sh
```

The Streamlit app is containerized with `Dockerfile`. To redeploy it from the repo root:

```bash
gcloud run deploy smartstudy-app \
  --project=smartstudy-h505 \
  --region=europe-west1 \
  --source=. \
  --allow-unauthenticated \
  --port=8080 \
  --service-account=376906403882-compute@developer.gserviceaccount.com \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=smartstudy-h505,GCP_LOCATION=europe-west1,GCS_BUCKET_NAME=smartstudy-h505-pdfs,MONGODB_DATABASE=smartstudy,MONGODB_COLLECTION=lecture_chunks,MONGODB_CHAT_COLLECTION=workspace_chats,MONGODB_VECTOR_INDEX=lecture_vector_index,EMBEDDING_MODEL=text-embedding-005,GEMINI_MODEL=gemini-2.5-flash,RETENTION_DAYS=7" \
  --set-secrets="MONGODB_URI=MONGODB_URI:latest" \
  --vpc-connector=smartstudy-vpc-conn \
  --vpc-egress=all-traffic
```

The Atlas Vector Search index includes `folder_id` and `folder_path` as filter fields. The index definition is in `docs/mongodb_vector_index.json`.

The bucket lifecycle rule for PDF cleanup is in `docs/gcs_lifecycle.json`. Apply it with:

```bash
gcloud storage buckets update gs://smartstudy-h505-pdfs \
  --lifecycle-file=docs/gcs_lifecycle.json
```

## Report

The final PDF report is in `docs/smartstudy_status_note.pdf`. A shorter architecture note is kept in `docs/architecture.md`.

## Submission status

The repo contains the Cloud Function, the Cloud Run Streamlit app, the LangChain retrieval code, the MongoDB Atlas Vector Search index definition, and the final PDF report required for the INFO-H505 submission.
