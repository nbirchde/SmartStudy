# SmartStudy architecture

SmartStudy has one deployed Streamlit app and one GCS-triggered Cloud Function.

Deployed app:

```text
https://smartstudy-app-376906403882.europe-west1.run.app/?folder_id=cb1b0a0c89744b3a8af605db9c3c58c1&folder_path=nicholas
```

## Flow

1. A user creates a folder in the Streamlit app.
2. The app creates a generated `folder_id` and stores it in the URL.
3. PDFs are uploaded to Cloud Storage under `folders/{folder_id}/{folder_path}/{upload_id}-{filename}.pdf`.
4. The Cloud Function ingests only PDFs under `folders/`.
5. Each MongoDB chunk stores `folder_id`, `folder_path`, `upload_id`, `source_file`, `gcs_path`, `page`, `chunk`, `uploaded_at`, and `expires_at`.
6. Workspace chat threads are stored in the `workspace_chats` MongoDB collection with the same `folder_id` and `folder_path` scope.
7. The chat retriever filters Atlas Vector Search by the active `folder_id` and `folder_path`.
8. Gemini 2.5 Flash answers from the retrieved chunks and active chat history. Lecture-specific claims still require retrieved source context.

## Data cleanup

Folder PDFs and indexed chunks are kept for 7 days.

- Cloud Storage deletes old objects under `folders/` through `docs/gcs_lifecycle.json`.
- MongoDB deletes old chunks through a TTL index on `expires_at`.

This is folder compartmentalization, not account-based security. Anyone with a folder URL can access that folder workspace and its persisted chat threads.
