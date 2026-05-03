# SmartStudy team notes

These notes are for us while we finish the project. They are not the final report.

## Current shape

The deployed app is here:

```text
https://smartstudy-app-rmbl7tljsq-ew.a.run.app
```

The main code files are:

- `app/app.py`: Streamlit upload and chat page. This is the Cloud Run entry point.
- `cloud_function/main.py`: Cloud Function that ingests PDFs after upload.
- `src/smartstudy/retriever.py`: MongoDB Atlas Vector Search retriever.
- `src/smartstudy/tutor.py`: Gemini tutor chain and prompt.

Current cloud resources:

- GCP project: `smartstudy-h505`
- Region: `europe-west1`
- Bucket: `gs://smartstudy-h505-pdfs/`
- Cloud Function: `ingest-pdf`
- Cloud Run app: `smartstudy-app`
- MongoDB collection: `smartstudy.lecture_chunks`
- Vector index: `lecture_vector_index`
- Static GCP egress IP: `104.155.37.123`

## Atlas IP access

The deployed app and function reach Atlas through:

```text
Cloud Run / Cloud Function -> VPC connector -> Cloud NAT -> 104.155.37.123 -> MongoDB Atlas
```

Atlas should keep:

```text
104.155.37.123/32  SmartStudy GCP NAT egress
```

Other IP entries are probably local developer IPs. Keep them only while someone runs the app or scripts from a laptop. For the shared online app, the GCP NAT IP is the one that matters.

## Secrets

Local development uses `.env`, which is ignored by Git.

Cloud Run and the Cloud Function read `MONGODB_URI` from Secret Manager. Do not paste the MongoDB URI into deploy commands, screenshots, or GitHub.

## How to test the app

1. Open the Cloud Run URL.
2. Upload a small PDF.
3. Wait for the indexing status to complete.
4. Ask a question that can be answered from the PDF.
5. Check that the answer cites a source file and page.

If indexing times out, check the Cloud Function logs. A healthy ingestion log looks like:

```text
Ingesting gs://smartstudy-h505-pdfs/<file>.pdf
Done: X chunks ingested from <file>.pdf
```

## Redeploying the app

The app deploy uses the repo `Dockerfile`.

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

## Things still to clean up

- Keep `app/app.py` as the deployed app, or remove/merge `app/streamlit_app.py`.
- Make indexing errors easier to understand in the UI.
- Show retrieved sources in the current app.
- Add a filter by PDF if retrieval keeps pulling from the wrong uploaded file.
- The bucket and MongoDB collection are shared right now. That means one user's chat can retrieve chunks from PDFs uploaded by someone else. A better next version would store files under user/session folders and filter retrieval by that scope.
- Keep the final report close to the rubric: automation, retrieval, architecture, tutor persona, and the web interface.
