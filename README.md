# SmartStudy Cloud Agent

SmartStudy is our INFO-H505 cloud project. A student uploads lecture PDFs, the system indexes the content, and a small tutor app answers questions using those notes.

The app is already deployed here:

```text
https://smartstudy-app-rmbl7tljsq-ew.a.run.app
```

## What it does

1. The student uploads a lecture PDF through the Streamlit app.
2. The app stores the PDF in Google Cloud Storage.
3. A Cloud Function runs automatically when the PDF arrives in the bucket.
4. The function extracts text, splits it into chunks, creates Vertex AI embeddings, and stores the chunks in MongoDB Atlas Vector Search.
5. The chat app retrieves the closest chunks for a question and sends them to Gemini 2.5 Flash.
6. Gemini answers as a formal academic tutor and cites the source file/page when the context supports it.

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
Vector index:      lecture_vector_index
Static egress IP:  104.155.37.123
```

The deployed app and function both read `MONGODB_URI` from Google Secret Manager. Their outbound MongoDB traffic goes through the VPC connector and Cloud NAT, so Atlas only needs to allow the static GCP egress IP.

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

The Streamlit app is containerized with `Dockerfile`. To redeploy it from the repo root:

```bash
gcloud run deploy smartstudy-app \
  --project=smartstudy-h505 \
  --region=europe-west1 \
  --source=. \
  --allow-unauthenticated \
  --port=8080 \
  --service-account=376906403882-compute@developer.gserviceaccount.com \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=smartstudy-h505,GCP_LOCATION=europe-west1,GCS_BUCKET_NAME=smartstudy-h505-pdfs,MONGODB_DATABASE=smartstudy,MONGODB_COLLECTION=lecture_chunks,MONGODB_VECTOR_INDEX=lecture_vector_index,EMBEDDING_MODEL=text-embedding-005,GEMINI_MODEL=gemini-2.5-flash" \
  --set-secrets="MONGODB_URI=MONGODB_URI:latest" \
  --vpc-connector=smartstudy-vpc-conn \
  --vpc-egress=all-traffic
```

## Useful docs

- `docs/team_notes.md`: short working notes for the team.
- `docs/smartstudy_status_note.pdf`: simple professor-facing implementation note.

## What is left

- Pick one Streamlit entry point. Right now `app/app.py` is the deployed one.
- Improve the app when indexing fails or takes too long.
- Show retrieved sources more clearly in the Cloud Run app.
- Add user/session scoping. Right now uploads and retrieval share one bucket/collection, so users can query PDFs uploaded by other people.
- Prepare the final report and demo around the rubric: automation, retrieval, architecture, tutor persona, and the web interface.
