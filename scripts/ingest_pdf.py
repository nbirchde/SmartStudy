import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pymongo import MongoClient, UpdateOne
from pypdf import PdfReader
import vertexai
from vertexai.language_models import TextEmbeddingModel


def read_pages(pdf_path: Path):
    reader = PdfReader(str(pdf_path))
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            yield page_number, text


def make_chunks(pdf_path: Path):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
    )

    for page_number, text in read_pages(pdf_path):
        for chunk_number, text_chunk in enumerate(splitter.split_text(text), start=1):
            yield {
                "text": text_chunk,
                "source_file": pdf_path.name,
                "page": page_number,
                "chunk": chunk_number,
            }


def embed_texts(texts, model_name: str):
    model = TextEmbeddingModel.from_pretrained(model_name)
    embeddings = []

    for start in range(0, len(texts), 16):
        batch = texts[start : start + 16]
        embeddings.extend(item.values for item in model.get_embeddings(batch))

    return embeddings


def ingest(pdf_path: Path):
    load_dotenv()

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GCP_LOCATION", "europe-west1")
    model_name = os.environ.get("EMBEDDING_MODEL", "text-embedding-005")
    mongo_uri = os.environ["MONGODB_URI"]
    database_name = os.environ.get("MONGODB_DATABASE", "smartstudy")
    collection_name = os.environ.get("MONGODB_COLLECTION", "lecture_chunks")

    chunks = list(make_chunks(pdf_path))
    if not chunks:
        raise SystemExit(f"No text found in {pdf_path}")

    vertexai.init(project=project, location=location)
    texts = [chunk["text"] for chunk in chunks]
    embeddings = embed_texts(texts, model_name)

    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding

    mongo = MongoClient(mongo_uri)
    collection = mongo[database_name][collection_name]
    collection.delete_many({"source_file": pdf_path.name})

    collection.bulk_write(
        [
            UpdateOne(
                {
                    "source_file": chunk["source_file"],
                    "page": chunk["page"],
                    "chunk": chunk["chunk"],
                },
                {"$set": chunk},
                upsert=True,
            )
            for chunk in chunks
        ]
    )

    print(f"Ingested {len(chunks)} chunks from {pdf_path.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    ingest(args.pdf)


if __name__ == "__main__":
    main()
