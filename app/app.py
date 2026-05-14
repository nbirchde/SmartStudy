import html
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from dotenv import load_dotenv
from google.cloud import storage
from pymongo import MongoClient

from src.smartstudy.chats import ChatStore, make_chat_message
from src.smartstudy.retriever import build_retriever
from src.smartstudy.tutor import build_chain

load_dotenv()

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.environ.get("GCP_LOCATION", "europe-west1")
BUCKET = os.environ.get("GCS_BUCKET_NAME", "")
MONGO_URI = os.environ.get("MONGODB_URI", "")
DATABASE = os.environ.get("MONGODB_DATABASE", "smartstudy")
COLLECTION = os.environ.get("MONGODB_COLLECTION", "lecture_chunks")
CHAT_COLLECTION = os.environ.get("MONGODB_CHAT_COLLECTION", "workspace_chats")
INDEX = os.environ.get("MONGODB_VECTOR_INDEX", "lecture_vector_index")
EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-005")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "7"))

POLL_TIMEOUT_S = 300
DEFAULT_WORKSPACE_PATH = "main"
FOLDER_ROOT = "folders"
MONGO_TIMEOUT_MS = 350
MONGO_COOLDOWN_S = 30


class FileStatus(TypedDict):
    files: list[str]
    available: bool
    error: str | None


class FolderStatus(TypedDict):
    paths: list[str]
    available: bool
    error: str | None


class ChatStatus(TypedDict):
    chats: list[dict]
    available: bool
    error: str | None


def _safe_segment(value: str, fallback: str = "workspace") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned or fallback


def _safe_folder_path(value: str) -> str:
    parts = [_safe_segment(part) for part in value.split("/") if part.strip()]
    return "/".join(parts) or DEFAULT_WORKSPACE_PATH


def _safe_filename(value: str) -> str:
    original = Path(value).name
    stem = _safe_segment(Path(original).stem, "document")
    return f"{stem}.pdf"


def _query_param(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _set_query_param(name: str, value: str | None) -> None:
    if value is None:
        if name in st.query_params:
            st.query_params.pop(name)
        return
    if st.query_params.get(name) != value:
        st.query_params[name] = value


def _set_current_workspace(folder_path: str) -> None:
    st.session_state.folder_path = _safe_folder_path(folder_path).split("/", 1)[0]
    st.session_state.created_folder_paths.add(st.session_state.folder_path)
    st.session_state.active_chat_id = None
    st.session_state.workspace_input_nonce = uuid.uuid4().hex
    _set_query_param("folder_path", st.session_state.folder_path)
    _set_query_param("chat_id", None)


def _open_chat(chat_id: str) -> None:
    st.session_state.active_chat_id = chat_id
    _set_query_param("chat_id", chat_id)


def _close_chat() -> None:
    st.session_state.active_chat_id = None
    _set_query_param("chat_id", None)


def _ensure_folder_state() -> None:
    folder_id = _query_param("folder_id")
    folder_path = _query_param("folder_path")
    chat_id = _query_param("chat_id")

    if "folder_id" not in st.session_state:
        st.session_state.folder_id = _safe_segment(folder_id or uuid.uuid4().hex, "folder")
    if "folder_path" not in st.session_state:
        st.session_state.folder_path = _safe_folder_path(folder_path or DEFAULT_WORKSPACE_PATH).split("/", 1)[0]
    if "created_folder_paths" not in st.session_state:
        st.session_state.created_folder_paths = set()
    if "workspace_input_nonce" not in st.session_state:
        st.session_state.workspace_input_nonce = uuid.uuid4().hex
    if "chat_input_nonce" not in st.session_state:
        st.session_state.chat_input_nonce = uuid.uuid4().hex
    if "uploads" not in st.session_state:
        st.session_state.uploads = []
    if "active_chat_id" not in st.session_state:
        st.session_state.active_chat_id = chat_id
    if "local_chats" not in st.session_state:
        st.session_state.local_chats = {}

    st.session_state.created_folder_paths.add(st.session_state.folder_path)
    _set_query_param("folder_id", st.session_state.folder_id)
    _set_query_param("folder_path", st.session_state.folder_path)
    if st.session_state.active_chat_id:
        _set_query_param("chat_id", st.session_state.active_chat_id)


def _workspace_key() -> str:
    return f"{st.session_state.folder_id}:{st.session_state.folder_path}"


def _folder_ready() -> bool:
    return bool(st.session_state.get("folder_id"))


def _make_object_name(uploaded_name: str) -> tuple[str, str, str]:
    upload_id = uuid.uuid4().hex[:12]
    safe_name = _safe_filename(uploaded_name)
    object_name = f"{FOLDER_ROOT}/{st.session_state.folder_id}/{st.session_state.folder_path}/{upload_id}-{safe_name}"
    return object_name, upload_id, safe_name


@st.cache_resource(show_spinner=False)
def _mongo_client() -> MongoClient:
    return MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=MONGO_TIMEOUT_MS,
        connectTimeoutMS=MONGO_TIMEOUT_MS,
        socketTimeoutMS=MONGO_TIMEOUT_MS,
    )


@st.cache_resource(show_spinner=False)
def _chat_store() -> ChatStore:
    store = ChatStore(_mongo_client()[DATABASE][CHAT_COLLECTION])
    try:
        store.ensure_indexes()
    except Exception:
        pass
    return store


def _workspace_title(folder_path: str) -> str:
    return folder_path.split("/", 1)[0] or DEFAULT_WORKSPACE_PATH


def _format_datetime(value: datetime | str | None) -> str:
    if not value:
        return "Just now"
    if isinstance(value, str):
        return value[:16]
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - value.astimezone(timezone.utc)
    if delta.total_seconds() < 60:
        return "Just now"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)} min ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() // 3600)} hr ago"
    return value.strftime("%b %-d")



def _mongo_alive() -> bool:
    until = st.session_state.get("_mongo_down_until", 0.0)
    return time.time() >= until


def _mark_mongo_down() -> None:
    st.session_state["_mongo_down_until"] = time.time() + MONGO_COOLDOWN_S


@st.cache_data(ttl=15, show_spinner=False)
def _mongo_folder_paths(folder_id: str) -> tuple[list[str], str | None]:
    try:
        col = _mongo_client()[DATABASE][COLLECTION]
        paths = col.distinct("folder_path", {"folder_id": folder_id})
        return sorted({str(path).split("/", 1)[0] for path in paths if path}), None
    except Exception as exc:
        return [], str(exc)


@st.cache_data(ttl=15, show_spinner=False)
def _mongo_folder_files(folder_id: str, folder_path: str) -> tuple[list[str], str | None]:
    try:
        col = _mongo_client()[DATABASE][COLLECTION]
        files = col.distinct("source_file", {"folder_id": folder_id, "folder_path": folder_path})
        return sorted(str(file) for file in files), None
    except Exception as exc:
        return [], str(exc)


@st.cache_data(ttl=30, show_spinner=False)
def _mongo_chat_list(folder_id: str, folder_path: str) -> tuple[list[dict], str | None]:
    try:
        return _chat_store().list_chats(folder_id, folder_path), None
    except Exception as exc:
        return [], str(exc)


def _folder_path_status(folder_id: str) -> FolderStatus:
    if not _mongo_alive():
        paths = set(st.session_state.created_folder_paths)
        paths.add(DEFAULT_WORKSPACE_PATH)
        return {"paths": sorted(p for p in paths if p), "available": False, "error": "mongo cooldown"}
    mongo_paths, error = _mongo_folder_paths(folder_id)
    if error:
        _mark_mongo_down()
    paths = set(mongo_paths)
    paths.update(str(path).split("/", 1)[0] for path in st.session_state.created_folder_paths)
    paths.add(DEFAULT_WORKSPACE_PATH)
    return {"paths": sorted(path for path in paths if path), "available": error is None, "error": error}


def _folder_file_status(folder_id: str, folder_path: str) -> FileStatus:
    if not _mongo_alive():
        return {"files": [], "available": False, "error": "mongo cooldown"}
    files, error = _mongo_folder_files(folder_id, folder_path)
    if error:
        _mark_mongo_down()
    return {"files": files, "available": error is None, "error": error}


def _local_workspace_chats() -> list[dict]:
    return list(st.session_state.local_chats.get(_workspace_key(), {}).values())


def _chat_status(folder_id: str, folder_path: str) -> ChatStatus:
    if not _mongo_alive():
        chats = sorted(_local_workspace_chats(), key=lambda chat: chat["updated_at"], reverse=True)
        return {"chats": chats, "available": False, "error": "mongo cooldown"}
    chats, error = _mongo_chat_list(folder_id, folder_path)
    if error:
        _mark_mongo_down()
        chats = sorted(_local_workspace_chats(), key=lambda chat: chat["updated_at"], reverse=True)
    return {"chats": chats, "available": error is None, "error": error}


def _get_chat(chat_id: str) -> tuple[dict | None, str | None]:
    try:
        chat = _chat_store().get_chat(chat_id, st.session_state.folder_id, st.session_state.folder_path)
        return chat, None
    except Exception as exc:
        return st.session_state.local_chats.get(_workspace_key(), {}).get(chat_id), str(exc)


def _create_chat(user_message: dict, assistant_message: dict) -> tuple[str, str | None]:
    try:
        chat_id = _chat_store().create_chat(
            st.session_state.folder_id,
            st.session_state.folder_path,
            user_message,
            assistant_message,
        )
        _mongo_chat_list.clear()
        return chat_id, None
    except Exception as exc:
        chat_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        st.session_state.local_chats.setdefault(_workspace_key(), {})[chat_id] = {
            "chat_id": chat_id,
            "folder_id": st.session_state.folder_id,
            "folder_path": st.session_state.folder_path,
            "title": user_message["content"][:60] or "New chat",
            "messages": [user_message, assistant_message],
            "created_at": now,
            "updated_at": now,
        }
        return chat_id, str(exc)


def _append_exchange(chat_id: str, user_message: dict, assistant_message: dict) -> str | None:
    try:
        _chat_store().append_exchange(
            chat_id,
            st.session_state.folder_id,
            st.session_state.folder_path,
            user_message,
            assistant_message,
        )
        _mongo_chat_list.clear()
        return None
    except Exception as exc:
        chat = st.session_state.local_chats.get(_workspace_key(), {}).get(chat_id)
        if chat:
            chat["messages"].extend([user_message, assistant_message])
            chat["updated_at"] = datetime.now(timezone.utc)
        return str(exc)


def _delete_chat(chat_id: str) -> None:
    try:
        _chat_store().delete_chat(chat_id, st.session_state.folder_id, st.session_state.folder_path)
        _mongo_chat_list.clear()
    except Exception:
        st.session_state.local_chats.get(_workspace_key(), {}).pop(chat_id, None)
    if st.session_state.active_chat_id == chat_id:
        _close_chat()


def _is_indexed(gcs_path: str) -> bool:
    try:
        col = _mongo_client()[DATABASE][COLLECTION]
        return col.count_documents({"gcs_path": gcs_path}, limit=1) > 0
    except Exception:
        return False


def _empty_context_answer(metadata_available: bool) -> str:
    if metadata_available:
        return (
            "I can keep talking, but this workspace does not have any indexed PDFs yet. "
            "Upload lecture notes from the Sources tab and I will ground lecture-specific answers in those documents. "
            "For now, I can help you plan what to upload, organize a study workflow, or explain how this tutor uses a workspace.\n\n"
            "What material do you want this workspace to cover first?"
        )
    return (
        "I can keep talking, but I cannot check this workspace's indexed PDFs right now. "
        "If you just uploaded notes, give the cloud index a moment. I will avoid making lecture-specific claims until the workspace materials are available again.\n\n"
        "What would you like to organize while the materials reconnect?"
    )


def _answer_question(
    question: str,
    pdf_count: int,
    file_status: FileStatus,
    history: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    try:
        if pdf_count == 0 and file_status["available"]:
            return _empty_context_answer(metadata_available=True), []
        if not file_status["available"]:
            return _empty_context_answer(metadata_available=False), []
        result = get_chain(st.session_state.folder_id, st.session_state.folder_path).invoke(
            {"question": question, "history": history or []}
        )
        if isinstance(result, dict):
            return result.get("answer", ""), result.get("sources", [])
        return str(result), []
    except Exception as exc:
        return f"Error: {exc}", []


def _show_sources(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander("Sources used"):
        for source in sources:
            file_name = source.get("source_file", "unknown")
            page = source.get("page", "?")
            preview = source.get("preview", "").strip()
            st.markdown(f"**{file_name}**, page {page}")
            if preview:
                st.caption(preview)


@st.cache_resource(max_entries=10)
def get_chain(folder_id: str, folder_path: str):
    retriever = build_retriever(
        mongo_uri=MONGO_URI,
        database=DATABASE,
        collection_name=COLLECTION,
        index_name=INDEX,
        project=PROJECT,
        location=LOCATION,
        embedding_model=EMBED_MODEL,
        pre_filter={"folder_id": folder_id, "folder_path": folder_path},
    )
    return build_chain(retriever=retriever, project=PROJECT, location=LOCATION, model_name=GEMINI_MODEL)


def _folder_mark(opened: bool = False) -> str:
    state = " open" if opened else ""
    return f"""<span class="folder-mark{state}" aria-hidden="true">
  <svg viewBox="0 0 24 24">
    <path class="folder-body" d="M5.6 7h3.8a1 1 0 0 1 .77.36L11.5 8.6h6.9A1.6 1.6 0 0 1 20 10.2v6.2A1.6 1.6 0 0 1 18.4 18H5.6A1.6 1.6 0 0 1 4 16.4V8.6A1.6 1.6 0 0 1 5.6 7Z"/>
    <path class="folder-fold" d="M4.4 10.9h15.2"/>
  </svg>
</span>"""


def _inject_css() -> None:
    st.markdown(
        """
<style>
:root {
  --app-bg: #ffffff;
  --surface: #f7f7f5;
  --surface-soft: #f1f1f3;
  --surface-hover: #eeeeec;
  --surface-selected: #e5e5e2;
  --text: #2b2c36;
  --text-strong: #111114;
  --muted: #6d6f78;
  --border: rgba(17, 17, 20, 0.14);
  --accent: #ff474d;
  --input: #f1f1f3;
  --action-bg: #111114;
  --action-text: #ffffff;
  --shadow: 0 18px 44px rgba(0, 0, 0, 0.08);
}
.stApp {
  color-scheme: light;
}
html, body {
  background: var(--app-bg) !important;
  color: var(--text) !important;
}
.stApp, div[data-testid="stAppViewContainer"], div[data-testid="stMain"] {
  background: var(--app-bg) !important;
  color: var(--text) !important;
}
header[data-testid="stHeader"],
div[data-testid="stDecoration"],
div[data-testid="stToolbar"] {
  background: var(--app-bg) !important;
  color: var(--text) !important;
}
div[data-testid="stAppViewContainer"] .main .block-container {
  max-width: 980px;
  padding: 3.25rem 1rem 6rem 1rem;
}
div[data-testid="stToolbar"] { right: 1.2rem; color: var(--text); }
[data-testid="stMainMenu"] { display: none !important; }
div[data-testid="stMain"] .stButton > button {
  background: var(--app-bg) !important;
  color: var(--text-strong) !important;
  border-color: var(--border) !important;
}
div[data-testid="stMain"] .stButton > button:hover {
  background: var(--surface-hover) !important;
  border-color: var(--border) !important;
}
div[data-testid="stMain"] .stButton > button:disabled {
  background: var(--surface-soft) !important;
  color: var(--muted) !important;
  border-color: var(--border) !important;
}
div[data-testid="stAlert"] {
  background: var(--surface-soft) !important;
  color: var(--text) !important;
  border-color: var(--border) !important;
}
div[data-testid="stTabs"] [role="tab"] {
  color: var(--text) !important;
}
div[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: var(--accent) !important;
}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
  background-color: var(--accent) !important;
}
div[data-testid="stTabs"] [data-baseweb="tab-border"] {
  background-color: var(--border) !important;
}
section[data-testid="stSidebar"] {
  border-right: 1px solid var(--border);
  background: var(--surface) !important;
}
section[data-testid="stSidebar"] > div {
  padding-top: 1.35rem;
  background: var(--surface) !important;
}
section[data-testid="stSidebar"] .stButton > button {
  min-height: 2.55rem;
  border-radius: 13px;
  border-color: transparent;
  justify-content: flex-start;
  font-weight: 480;
  background: transparent !important;
  color: var(--text) !important;
  padding-left: 2.85rem;
  position: relative;
  transition: background 160ms ease, color 160ms ease;
}
section[data-testid="stSidebar"] .stButton > button::before {
  content: "";
  position: absolute;
  left: 0.9rem;
  top: calc(50% - 0.675rem);
  width: 1.35rem;
  height: 1.35rem;
  background: currentColor;
  opacity: 0.78;
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M5.6 7h3.8a1 1 0 0 1 .77.36L11.5 8.6h6.9A1.6 1.6 0 0 1 20 10.2v6.2A1.6 1.6 0 0 1 18.4 18H5.6A1.6 1.6 0 0 1 4 16.4V8.6A1.6 1.6 0 0 1 5.6 7Z' fill='none' stroke='black' stroke-width='1.45' stroke-linejoin='round'/%3E%3Cpath d='M4.4 10.9h15.2' fill='none' stroke='black' stroke-width='1.45' stroke-linecap='round'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M5.6 7h3.8a1 1 0 0 1 .77.36L11.5 8.6h6.9A1.6 1.6 0 0 1 20 10.2v6.2A1.6 1.6 0 0 1 18.4 18H5.6A1.6 1.6 0 0 1 4 16.4V8.6A1.6 1.6 0 0 1 5.6 7Z' fill='none' stroke='black' stroke-width='1.45' stroke-linejoin='round'/%3E%3Cpath d='M4.4 10.9h15.2' fill='none' stroke='black' stroke-width='1.45' stroke-linecap='round'/%3E%3C/svg%3E") center / contain no-repeat;
  transition: opacity 160ms ease, transform 200ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
section[data-testid="stSidebar"] .stButton > button:hover {
  background: var(--surface-hover) !important;
  border-color: transparent;
}
section[data-testid="stSidebar"] .stButton > button:hover::before {
  opacity: 1;
  transform: translateY(-1px) scale(1.06);
}
section[data-testid="stSidebar"] div[data-testid="stForm"] button {
  background: var(--action-bg) !important;
  color: var(--action-text) !important;
  border-color: var(--action-bg) !important;
  justify-content: center !important;
  padding-left: 0.75rem !important;
}
section[data-testid="stSidebar"] div[data-testid="stForm"] button::before {
  display: none !important;
}
section[data-testid="stSidebar"] div[data-testid="stForm"] button:disabled {
  background: var(--surface-soft) !important;
  color: var(--muted) !important;
  border-color: transparent !important;
}
input, textarea, div[data-baseweb="input"] {
  color: var(--text-strong) !important;
}
input, textarea,
div[data-baseweb="input"],
div[data-baseweb="textarea"],
div[data-baseweb="base-input"],
div[data-testid="stTextInput"] > div,
div[data-testid="stTextArea"] > div {
  background: var(--input) !important;
  border-color: var(--border) !important;
  color: var(--text-strong) !important;
}
div[data-baseweb="input"] *,
div[data-baseweb="textarea"] *,
div[data-testid="stTextInput"] *,
div[data-testid="stTextArea"] * {
  color: var(--text-strong) !important;
}
input::placeholder, textarea::placeholder {
  color: var(--muted) !important;
  opacity: 1 !important;
}
label, p, span, h1, h2, h3, h4, h5, h6 {
  color: inherit;
}
.rail-title {
  font-size: 1.38rem;
  font-weight: 730;
  margin: 0.2rem 0 1.6rem 0;
  color: var(--text-strong);
}
.rail-section {
  font-size: 0.9rem;
  font-weight: 680;
  margin: 1.2rem 0 0.55rem 0;
  color: var(--text);
}
.rail-active, .workspace-pill {
  display: flex;
  align-items: center;
  gap: 0.72rem;
  border-radius: 14px;
  color: var(--text-strong);
  padding: 0.78rem 0.85rem;
  font-weight: 620;
  margin: 0.22rem 0 0.45rem 0;
  width: 100%;
}
.rail-active {
  background: var(--surface-selected);
}
.rail-active .folder-mark {
  color: var(--accent);
}
.workspace-pill {
  background: transparent;
  text-decoration: none !important;
  color: var(--text-strong) !important;
  transition: background 160ms ease, transform 160ms ease;
}
.workspace-pill:visited, .workspace-pill:active {
  color: var(--text-strong) !important;
}
.workspace-pill:hover {
  background: var(--surface-hover);
  transform: translateX(1px);
}
.folder-mark {
  position: relative;
  width: 1.35rem;
  height: 1.35rem;
  flex: 0 0 auto;
  color: var(--text-strong);
}
.folder-mark svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.45;
  stroke-linecap: round;
  stroke-linejoin: round;
  overflow: visible;
}
.folder-mark {
  transition: transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.folder-mark .folder-fold {
  transition: transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 200ms ease;
  opacity: 0.85;
}
.workspace-pill:hover .folder-mark,
.rail-active .folder-mark {
  transform: translateY(-1px) scale(1.06);
}
.workspace-pill:hover .folder-mark .folder-fold,
.folder-mark.open .folder-fold {
  transform: translateY(1.2px);
  opacity: 1;
}
.folder-mark.open {
  color: var(--accent);
}
.project-icon .folder-mark {
  width: 100%;
  height: 100%;
  color: var(--accent);
}
.project-icon .folder-mark svg {
  stroke-width: 1.6;
}
.rail-active span, .workspace-pill span {
  overflow: hidden;
  text-overflow: ellipsis;
}
.rail-mini {
  border-top: 1px solid var(--border);
  padding-top: 0.9rem;
  margin-top: 1.2rem;
}
.rail-session {
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.35;
  margin-top: 0.7rem;
}
.project-shell {
  max-width: 850px;
  margin-left: auto;
  margin-right: auto;
}
.project-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin: 1.85rem 0 1.65rem 0;
}
.project-icon {
  width: 42px;
  height: 42px;
  display: inline-flex;
  color: var(--text-strong);
}
.project-title {
  font-size: 2.05rem;
  line-height: 1.08;
  font-weight: 580;
  letter-spacing: 0;
  margin: 0;
  color: var(--text-strong);
}
.project-subtitle {
  color: var(--muted);
  font-size: 0.95rem;
  margin-top: 0.3rem;
}
.home-composer {
  margin: 0 0 1.8rem 0;
}
.home-composer div[data-testid="stForm"] {
  border: 0;
}
.home-composer .stButton > button {
  min-height: 3rem;
  border-radius: 16px;
  justify-content: center;
  background: var(--app-bg) !important;
  color: var(--text-strong) !important;
  border-color: var(--border) !important;
}
.chat-list {
  border-top: 1px solid var(--border);
  margin-top: 0.35rem;
}
.chat-row {
  display: flex;
  align-items: center;
  gap: 0.78rem;
  min-height: 3.4rem;
  padding: 0.7rem 0.2rem;
  color: var(--text);
}
.chat-row-shell {
  border-bottom: 1px solid var(--border);
  transition: background 150ms ease;
}
.chat-row-shell:hover {
  background: var(--surface-soft);
}
.chat-title {
  color: var(--text-strong);
  font-weight: 560;
}
.chat-meta {
  color: var(--muted);
  font-size: 0.82rem;
  margin-top: 0.16rem;
}
.chat-trash button {
  width: 2.15rem !important;
  min-height: 2.15rem !important;
  border-radius: 50% !important;
  padding: 0 !important;
  justify-content: center !important;
  opacity: 0.68;
  transition: opacity 140ms ease, background 140ms ease, transform 140ms ease;
}
.chat-trash button:hover {
  opacity: 1;
  background: color-mix(in srgb, var(--accent) 14%, transparent) !important;
  color: var(--accent) !important;
  transform: scale(1.04);
}
.source-empty {
  border: 1.5px dashed var(--border);
  border-radius: 18px;
  min-height: 240px;
  display: grid;
  place-items: center;
  text-align: center;
  padding: 2rem;
  margin-top: 1.2rem;
  color: var(--muted);
}
.source-empty h3 {
  color: var(--text-strong);
  font-size: 1.2rem;
  font-weight: 620;
  margin: 0.75rem 0 0.35rem 0;
}
.source-icons span {
  width: 42px;
  height: 42px;
  border: 1px solid var(--border);
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-soft);
}
.source-row {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.65rem 0;
  border-top: 1px solid var(--border);
  color: var(--text);
}
.tab-caption, .meta-line {
  color: var(--muted);
  font-size: 0.9rem;
  margin-top: 0.7rem;
}
.chat-empty {
  color: var(--muted);
  text-align: center;
  padding: 3rem 1rem 1.5rem 1rem;
}
.chat-empty strong {
  display: block;
  color: var(--text-strong);
  font-size: 1.06rem;
  margin-bottom: 0.35rem;
}
.back-row {
  margin: 0.1rem 0 1.2rem 0;
}
.back-row button {
  border-radius: 50% !important;
  width: 2.4rem !important;
  min-height: 2.4rem !important;
  padding: 0 !important;
  justify-content: center !important;
  background: var(--app-bg) !important;
  color: var(--text-strong) !important;
  border-color: var(--border) !important;
}
div[data-testid="stChatMessage"],
div[data-testid="stChatMessage"] *,
div[data-testid="stChatInput"] {
  color: var(--text) !important;
}
div[data-testid="stChatMessage"],
div[data-testid="stChatInput"] {
  background: var(--app-bg) !important;
}
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] [data-baseweb="textarea"] {
  background: var(--input) !important;
  color: var(--text-strong) !important;
  border-color: var(--border) !important;
}
@media (max-width: 900px) {
  div[data-testid="stAppViewContainer"] .main .block-container {
    padding-left: 1rem;
    padding-right: 1rem;
  }
  .project-shell { max-width: none; }
  .project-title { font-size: 1.72rem; }
  .project-header { margin-top: 1rem; }
}
</style>
""",
        unsafe_allow_html=True,
    )


def _render_sidebar(folder_status: FolderStatus, file_status: FileStatus, chat_status: ChatStatus) -> None:
    with st.sidebar:
        st.markdown('<div class="rail-title">SmartStudy</div>', unsafe_allow_html=True)
        st.markdown('<div class="rail-section">Workspaces</div>', unsafe_allow_html=True)
        current_path = st.session_state.folder_path
        for workspace_path in folder_status["paths"]:
            workspace_title = html.escape(_workspace_title(workspace_path))
            if workspace_path == current_path:
                st.markdown(
                    f'<div class="rail-active">{_folder_mark(opened=True)}<span>{workspace_title}</span></div>',
                    unsafe_allow_html=True,
                )
            else:
                if st.button(
                    _workspace_title(workspace_path),
                    key=f"workspace_nav_{workspace_path}",
                    use_container_width=True,
                ):
                    _set_current_workspace(workspace_path)
                    st.rerun()

        with st.form("new_workspace_form", border=False):
            workspace_name = st.text_input(
                "New workspace",
                value="",
                placeholder="New workspace",
                key=f"workspace_input_{st.session_state.workspace_input_nonce}",
                label_visibility="collapsed",
            )
            if st.form_submit_button("Create", icon=":material/add:", use_container_width=True):
                if workspace_name.strip():
                    _set_current_workspace(_safe_segment(workspace_name, "workspace"))
                    st.rerun()

        st.markdown('<div class="rail-mini">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="rail-session">{len(file_status["files"])} sources · {len(chat_status["chats"])} chats</div>',
            unsafe_allow_html=True,
        )
        if not chat_status["available"]:
            st.markdown('<div class="rail-session">Chat history is reconnecting; this browser can still continue locally.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="rail-session">Share the URL to invite teammates into this workspace.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_pending_indexing() -> None:
    if "pending_gcs_path" not in st.session_state:
        return
    fname = st.session_state.pending_file
    gcs_path = st.session_state.pending_gcs_path
    elapsed = time.time() - st.session_state.pending_since
    if _is_indexed(gcs_path):
        st.success(f"{fname} is ready.")
        for key in ("pending_file", "pending_gcs_path", "pending_since"):
            st.session_state.pop(key, None)
        _mongo_folder_files.clear()
        return
    if elapsed > POLL_TIMEOUT_S:
        st.warning(f"{fname} is still indexing. Check Cloud Function logs if it does not appear soon.")
        for key in ("pending_file", "pending_gcs_path", "pending_since"):
            st.session_state.pop(key, None)
        return
    left, right = st.columns([5, 1])
    with left:
        st.info(f"Indexing {fname}. You can keep using the app while it runs.")
    with right:
        if st.button("Refresh", use_container_width=True):
            st.rerun()


def _render_header(project_title: str, pdf_count: int, chat_count: int) -> None:
    escaped_title = html.escape(project_title)
    st.markdown(
        f"""<div class="project-header">
<div class="project-icon">{_folder_mark(opened=True)}</div>
<div>
  <h1 class="project-title">{escaped_title}</h1>
  <div class="project-subtitle">{html.escape(st.session_state.folder_path)} · {pdf_count} sources · {chat_count} chats</div>
</div>
</div>""",
        unsafe_allow_html=True,
    )


def _render_home(project_title: str, file_status: FileStatus, chat_status: ChatStatus) -> None:
    pdf_count = len(file_status["files"])
    _render_header(project_title, pdf_count, len(chat_status["chats"]))

    st.markdown('<div class="home-composer">', unsafe_allow_html=True)
    with st.form(f"new_chat_form_{st.session_state.workspace_input_nonce}", border=False):
        ask_col, send_col = st.columns([8, 1])
        with ask_col:
            question = st.text_input(
                "Ask SmartStudy",
                placeholder=f"New question in {project_title}",
                label_visibility="collapsed",
            )
        with send_col:
            submitted = st.form_submit_button("Ask", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if submitted and question.strip():
        user_message = make_chat_message("user", question.strip())
        with st.spinner("Thinking..."):
            answer, sources = _answer_question(question.strip(), pdf_count, file_status, [])
        assistant_message = make_chat_message("assistant", answer, sources)
        chat_id, error = _create_chat(user_message, assistant_message)
        if error:
            st.toast("Cloud chat history is reconnecting; saved locally for this browser.")
        _open_chat(chat_id)
        st.rerun()

    chat_tab, sources_tab = st.tabs(["Chats", "Sources"])
    with chat_tab:
        if chat_status["chats"]:
            st.markdown('<div class="chat-list">', unsafe_allow_html=True)
            for chat in chat_status["chats"]:
                chat_id = chat["chat_id"]
                last_message = (chat.get("messages") or [{}])[-1]
                st.markdown('<div class="chat-row-shell">', unsafe_allow_html=True)
                open_col, delete_col = st.columns([10, 1])
                with open_col:
                    if st.button(
                        chat.get("title") or "New chat",
                        key=f"open-chat-{chat_id}",
                        icon=":material/chat_bubble:",
                        use_container_width=True,
                    ):
                        _open_chat(chat_id)
                        st.rerun()
                    st.markdown(
                        f'<div class="chat-meta">{html.escape(_format_datetime(chat.get("updated_at")))} · {html.escape(str(last_message.get("role", "chat")))}</div>',
                        unsafe_allow_html=True,
                    )
                with delete_col:
                    st.markdown('<div class="chat-trash">', unsafe_allow_html=True)
                    if st.button("", icon=":material/delete:", key=f"delete-chat-{chat_id}", help="Delete chat"):
                        _delete_chat(chat_id)
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown(
                """<div class="chat-empty">
<strong>No chats in this workspace yet</strong>
Ask a question above to start a separate conversation in this workspace.
</div>""",
                unsafe_allow_html=True,
            )
        if not chat_status["available"]:
            st.caption("Cloud chat history is reconnecting. New chats will stay local in this browser until MongoDB is reachable.")

    with sources_tab:
        _render_sources(file_status)


def _render_sources(file_status: FileStatus) -> None:
    if not file_status["files"]:
        st.markdown(
            """<div class="source-empty">
<div>
  <div class="source-icons"><span>PDF</span></div>
  <h3>Give SmartStudy more context</h3>
  <p>Upload lecture PDFs so the tutor can answer from this workspace's sources.</p>
</div>
</div>""",
            unsafe_allow_html=True,
        )
    uploaded = st.file_uploader("PDF lecture notes", type=["pdf"])
    if uploaded and st.button("Add source", type="primary"):
        try:
            uploaded.seek(0)
            object_name, upload_id, safe_name = _make_object_name(uploaded.name)
            blob = storage.Client(project=PROJECT).bucket(BUCKET).blob(object_name)
            blob.metadata = {
                "folder_id": st.session_state.folder_id,
                "folder_path": st.session_state.folder_path,
                "upload_id": upload_id,
                "source_file": safe_name,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            with st.spinner(f"Uploading {safe_name}…"):
                blob.upload_from_file(uploaded, content_type="application/pdf")
            st.session_state.pending_file = safe_name
            st.session_state.pending_gcs_path = object_name
            st.session_state.pending_since = time.time()
            st.session_state.uploads.append({"source_file": safe_name, "gcs_path": object_name})
            st.rerun()
        except Exception as exc:
            st.error(f"Upload failed: {exc}")

    if file_status["files"]:
        for file_name in file_status["files"]:
            st.markdown(
                f'<div class="source-row"><span>PDF</span><span>{html.escape(file_name)}</span></div>',
                unsafe_allow_html=True,
            )
    elif not file_status["available"]:
        st.markdown('<div class="tab-caption">Sources are unavailable while cloud metadata reconnects.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="tab-caption">No indexed PDFs in this workspace yet.</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="meta-line">PDFs and indexed chunks are retained for {RETENTION_DAYS} days.</div>',
        unsafe_allow_html=True,
    )


def _render_chat_view(project_title: str, file_status: FileStatus, chat_id: str) -> None:
    chat, error = _get_chat(chat_id)
    if not chat:
        st.warning("This chat could not be found.")
        if st.button("Back to chats", icon=":material/arrow_back:"):
            _close_chat()
            st.rerun()
        return

    back_col, title_col = st.columns([1, 10])
    with back_col:
        st.markdown('<div class="back-row">', unsafe_allow_html=True)
        if st.button("", icon=":material/arrow_back:", key="back-to-chats", help="Back to chats"):
            _close_chat()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with title_col:
        st.markdown(
            f"""<div>
  <h1 class="project-title">{html.escape(chat.get("title", project_title))}</h1>
  <div class="project-subtitle">{html.escape(project_title)} · {len(file_status["files"])} sources</div>
</div>""",
            unsafe_allow_html=True,
        )

    if error:
        st.caption("Cloud chat history is reconnecting; showing any local copy available in this browser.")

    messages = chat.get("messages", [])
    for msg in messages:
        with st.chat_message(msg.get("role", "user")):
            st.markdown(msg.get("content", ""))
            if msg.get("role") == "assistant":
                _show_sources(msg.get("sources", []))

    prompt = st.chat_input(
        f"Message {chat.get('title', project_title)}",
        key=f"chat_input_{chat_id}_{st.session_state.chat_input_nonce}",
    )
    if prompt and prompt.strip():
        user_message = make_chat_message("user", prompt.strip())
        with st.spinner("Thinking..."):
            answer, sources = _answer_question(
                prompt.strip(),
                len(file_status["files"]),
                file_status,
                messages + [user_message],
            )
        assistant_message = make_chat_message("assistant", answer, sources)
        error = _append_exchange(chat_id, user_message, assistant_message)
        if error:
            st.toast("Cloud chat history is reconnecting; saved locally for this browser.")
        st.session_state.chat_input_nonce = uuid.uuid4().hex
        st.rerun()


st.set_page_config(page_title="SmartStudy", layout="wide")
_inject_css()
_ensure_folder_state()

folder_status: FolderStatus = {"paths": [DEFAULT_WORKSPACE_PATH], "available": True, "error": None}
file_status: FileStatus = {"files": [], "available": True, "error": None}
chat_status: ChatStatus = {"chats": [], "available": True, "error": None}

if _folder_ready():
    folder_status = _folder_path_status(st.session_state.folder_id)
    file_status = _folder_file_status(st.session_state.folder_id, st.session_state.folder_path)
    chat_status = _chat_status(st.session_state.folder_id, st.session_state.folder_path)

_render_sidebar(folder_status, file_status, chat_status)
_render_pending_indexing()

project_title = _workspace_title(st.session_state.folder_path)
st.markdown('<div class="project-shell">', unsafe_allow_html=True)
if st.session_state.active_chat_id:
    _render_chat_view(project_title, file_status, st.session_state.active_chat_id)
else:
    _render_home(project_title, file_status, chat_status)
st.markdown("</div>", unsafe_allow_html=True)
