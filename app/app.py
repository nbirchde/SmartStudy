import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from dotenv import load_dotenv
from google.cloud import storage
from pymongo import MongoClient

from src.smartstudy.retriever import build_retriever
from src.smartstudy.tutor import build_chain

load_dotenv()

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.environ.get("GCP_LOCATION", "europe-west1")
BUCKET = os.environ.get("GCS_BUCKET_NAME", "")
MONGO_URI = os.environ.get("MONGODB_URI", "")
DATABASE = os.environ.get("MONGODB_DATABASE", "smartstudy")
COLLECTION = os.environ.get("MONGODB_COLLECTION", "lecture_chunks")
INDEX = os.environ.get("MONGODB_VECTOR_INDEX", "lecture_vector_index")
EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-005")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

POLL_INTERVAL_S = 8
POLL_TIMEOUT_S = 300


def _is_indexed(filename: str) -> bool:
    client = MongoClient(MONGO_URI)
    try:
        col = client[DATABASE][COLLECTION]
        return col.count_documents({"source_file": filename}, limit=1) > 0
    finally:
        client.close()


st.set_page_config(page_title="SmartStudy")
st.title("SmartStudy - Academic Tutor")


@st.cache_resource
def get_chain():
    retriever = build_retriever(
        mongo_uri=MONGO_URI,
        database=DATABASE,
        collection_name=COLLECTION,
        index_name=INDEX,
        project=PROJECT,
        location=LOCATION,
        embedding_model=EMBED_MODEL,
    )
    return build_chain(
        retriever=retriever,
        project=PROJECT,
        location=LOCATION,
        model_name=GEMINI_MODEL,
    )


with st.sidebar:
    st.header("Upload Lecture Notes")

    uploaded = st.file_uploader("Choose a PDF", type=["pdf"])
    if uploaded and st.button("Upload to Cloud", type="primary"):
        try:
            uploaded.seek(0)
            gcs = storage.Client(project=PROJECT)
            blob = gcs.bucket(BUCKET).blob(uploaded.name)
            blob.upload_from_file(uploaded, content_type="application/pdf")
            st.session_state.pending_file = uploaded.name
            st.session_state.pending_since = time.time()
        except Exception as exc:
            st.error(f"Upload failed: {exc}")

    st.divider()
    if st.button("Clear chat history"):
        st.session_state.messages = []
        st.rerun()


# Ingestion progress tracker
if "pending_file" in st.session_state:
    fname = st.session_state.pending_file
    elapsed = time.time() - st.session_state.pending_since

    with st.status(f"Indexing **{fname}**...", expanded=True) as status:
        if _is_indexed(fname):
            status.update(label=f"**{fname}** is ready — you can start chatting!", state="complete")
            del st.session_state.pending_file
            del st.session_state.pending_since
        elif elapsed > POLL_TIMEOUT_S:
            status.update(label=f"Indexing **{fname}** is taking longer than expected. Check Cloud Function logs.", state="error")
            del st.session_state.pending_file
            del st.session_state.pending_since
        else:
            st.write(f"Pipeline running… checked every {POLL_INTERVAL_S}s ({int(elapsed)}s elapsed)")
            time.sleep(POLL_INTERVAL_S)
            st.rerun()


# Main chat interface
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if question := st.chat_input("Ask your tutor a question about your lecture notes."):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                answer = get_chain().invoke(question)
            except Exception as exc:
                answer = f"Error: {exc}"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
