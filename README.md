# SmartStudy Cloud Agent

Starter repo for the INFO-H505 project.

The project idea is simple: a student uploads lecture PDFs, the system indexes the content, and a small tutor app answers questions using only those notes.

## Target

1. A student uploads a lecture PDF to a Google Cloud Storage bucket.
2. A Cloud Function reacts to the upload.
3. The function extracts text, cuts it into chunks, embeds the chunks with Vertex AI, and stores them in MongoDB Atlas Vector Search.
4. A small web app retrieves the most relevant chunks and sends them to Gemini 2.5 Flash.
5. The answer should cite the PDF/page and behave like an academic tutor, not a generic chatbot.

## Planned Layout

```text
smartstudy/
  app/                    Streamlit app, once we start the UI
  cloud_function/         GCS-triggered ingestion function
  docs/                   Architecture notes and report material
  src/smartstudy/         Shared retrieval / tutor code
```

## First Scope

We will keep the first version small:

- create the GCP project and upload bucket;
- create the MongoDB Atlas collection and vector index;
- write one ingestion function for PDFs;
- write one minimal chat page;
- make the demo work with one or two lecture PDFs.

## Required Cloud Services

- Google Cloud Storage
- Cloud Functions
- Vertex AI API
- MongoDB Atlas Vector Search
- Streamlit, at least locally for the demo

## Environment Variables

Copy `.env.example` to `.env` locally and fill in real values.

```bash
cp .env.example .env
```

Required values:

- `GOOGLE_CLOUD_PROJECT`
- `GCP_LOCATION`
- `GCS_BUCKET_NAME`
- `MONGODB_URI`
- `MONGODB_DATABASE`
- `MONGODB_COLLECTION`
- `MONGODB_VECTOR_INDEX`
- `EMBEDDING_MODEL`
- `GEMINI_MODEL`

## Local Setup

Once the first Python files exist, use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## MongoDB Vector Search Index

`docs/mongodb_vector_index.json` is the draft Atlas Vector Search index. We may need to adjust it after we choose the exact embedding model.

## Team Split

- Cloud: GCP project, bucket, APIs, Cloud Function deployment.
- Retrieval: PDF parsing, chunking, embeddings, MongoDB index.
- App: Streamlit upload/chat page.
- Report/demo: diagram, implementation summary, final slides.

## Grading Notes

The professor grades automation, retrieval quality, architecture, tutor behaviour, and one advanced feature. We are using the web interface as the advanced feature because it also helps the final demo.
