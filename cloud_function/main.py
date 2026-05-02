import os
import tempfile
from pathlib import Path

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import storage
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pymongo import MongoClient
from pypdf import PdfReader

# Cloud Function to ingest uploaded PDFs, extract text, create embeddings, and store them in MongoDB Atlas for retrieval by the tutor chain.
@functions_framework.cloud_event
def ingest_pdf(cloud_event: CloudEvent) -> None:
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]

    if not file_name.lower().endswith(".pdf"):
        print(f"Skipping non-PDF: {file_name}")
        return

    print(f"Ingesting gs://{bucket_name}/{file_name}")

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GCP_LOCATION", "europe-west1")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-005")
    mongo_uri = os.environ["MONGODB_URI"]
    database = os.environ.get("MONGODB_DATABASE", "smartstudy")
    collection_name = os.environ.get("MONGODB_COLLECTION", "lecture_chunks")
    index_name = os.environ.get("MONGODB_VECTOR_INDEX", "lecture_vector_index")

    blob = storage.Client().bucket(bucket_name).blob(file_name)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        blob.download_to_filename(tmp.name)
        tmp_path = tmp.name

    try:
        documents = _extract_documents(tmp_path, file_name)
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

        pdf_basename = Path(file_name).name
        deleted = collection.delete_many({"source_file": pdf_basename})
        if deleted.deleted_count:
            print(f"Removed {deleted.deleted_count} stale chunks for {pdf_basename}")

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

# Helper function to extract text from PDF, split into chunks, and create Document objects with metadata for MongoDB storage.
def _extract_documents(pdf_path: str, gcs_file_name: str) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    reader = PdfReader(pdf_path)
    pdf_basename = Path(gcs_file_name).name
    docs = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        for chunk_number, chunk_text in enumerate(splitter.split_text(text), start=1):
            docs.append(Document(
                page_content=chunk_text,
                metadata={
                    "source_file": pdf_basename,
                    "gcs_path": gcs_file_name,
                    "page": page_number,
                    "chunk": chunk_number,
                },
            ))

    return docs
