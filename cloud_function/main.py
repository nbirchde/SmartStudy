import os
import tempfile
from datetime import datetime, timedelta, timezone

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import storage
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pymongo import MongoClient
from pypdf import PdfReader

FOLDER_ROOT = "folders"


@functions_framework.cloud_event
def ingest_pdf(cloud_event: CloudEvent) -> None:
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]

    if not file_name.lower().endswith(".pdf"):
        print(f"Skipping non-PDF: {file_name}")
        return

    folder_info = _parse_folder_object(file_name)
    if not folder_info:
        print(f"Skipping PDF outside folder scope: {file_name}")
        return

    print(f"Ingesting gs://{bucket_name}/{file_name}")

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GCP_LOCATION", "europe-west1")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-005")
    mongo_uri = os.environ["MONGODB_URI"]
    database = os.environ.get("MONGODB_DATABASE", "smartstudy")
    collection_name = os.environ.get("MONGODB_COLLECTION", "lecture_chunks")
    index_name = os.environ.get("MONGODB_VECTOR_INDEX", "lecture_vector_index")
    retention_days = int(os.environ.get("RETENTION_DAYS", "7"))

    blob = storage.Client().bucket(bucket_name).blob(file_name)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        blob.download_to_filename(tmp.name)
        tmp_path = tmp.name

    try:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=retention_days)
        documents = _extract_documents(
            tmp_path,
            gcs_file_name=file_name,
            folder_id=folder_info["folder_id"],
            folder_path=folder_info["folder_path"],
            upload_id=folder_info["upload_id"],
            source_file=folder_info["source_file"],
            uploaded_at=now,
            expires_at=expires_at,
        )
        if not documents:
            print(f"No text found in {file_name}")
            return

        embeddings = GoogleGenerativeAIEmbeddings(
            model=embedding_model,
            project=project,
            location=location,
        )

        mongo_client = MongoClient(mongo_uri)
        collection = mongo_client[database][collection_name]
        _ensure_indexes(collection)

        deleted = collection.delete_many({"gcs_path": file_name})
        if deleted.deleted_count:
            print(f"Removed {deleted.deleted_count} stale chunks for {file_name}")

        vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embeddings,
            index_name=index_name,
            text_key="text",
            embedding_key="embedding",
        )
        vector_store.add_documents(documents)
        print(f"Done: {len(documents)} chunks ingested from {file_name}")

    except Exception as exc:
        print(f"ERROR ingesting {file_name}: {exc}")
        raise
    finally:
        os.unlink(tmp_path)


def _parse_folder_object(gcs_file_name: str) -> dict | None:
    parts = gcs_file_name.split("/")
    if len(parts) < 4 or parts[0] != FOLDER_ROOT:
        return None

    folder_id = parts[1]
    folder_path = "/".join(parts[2:-1])
    uploaded_name = parts[-1]
    upload_id, separator, source_file = uploaded_name.partition("-")
    if not separator or not folder_id or not folder_path or not source_file:
        return None

    return {
        "folder_id": folder_id,
        "folder_path": folder_path,
        "upload_id": upload_id,
        "source_file": source_file,
    }


def _ensure_indexes(collection) -> None:
    collection.create_index("gcs_path")
    collection.create_index("folder_id")
    collection.create_index([("folder_id", 1), ("folder_path", 1)])
    collection.create_index("expires_at", expireAfterSeconds=0)


def _extract_documents(
    pdf_path: str,
    gcs_file_name: str,
    folder_id: str,
    folder_path: str,
    upload_id: str,
    source_file: str,
    uploaded_at: datetime,
    expires_at: datetime,
) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    reader = PdfReader(pdf_path)
    docs = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        for chunk_number, chunk_text in enumerate(splitter.split_text(text), start=1):
            docs.append(Document(
                page_content=chunk_text,
                metadata={
                    "folder_id": folder_id,
                    "folder_path": folder_path,
                    "upload_id": upload_id,
                    "source_file": source_file,
                    "gcs_path": gcs_file_name,
                    "page": page_number,
                    "chunk": chunk_number,
                    "uploaded_at": uploaded_at,
                    "expires_at": expires_at,
                },
            ))

    return docs
