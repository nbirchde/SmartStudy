from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from pymongo import ASCENDING, DESCENDING


MAX_TITLE_LENGTH = 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_chat_title(message: str) -> str:
    title = " ".join(message.strip().split())
    if not title:
        return "New chat"
    if len(title) <= MAX_TITLE_LENGTH:
        return title
    return f"{title[: MAX_TITLE_LENGTH - 1].rstrip()}…"


def make_chat_message(role: str, content: str, sources: list[dict] | None = None) -> dict:
    message: dict[str, Any] = {
        "role": role,
        "content": content,
        "created_at": utc_now(),
    }
    if sources:
        message["sources"] = sources
    return message


class ChatStore:
    def __init__(self, collection):
        self.collection = collection

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("folder_id", ASCENDING), ("folder_path", ASCENDING), ("updated_at", DESCENDING)]
        )
        self.collection.create_index("chat_id", unique=True)

    def list_chats(self, folder_id: str, folder_path: str, limit: int = 50) -> list[dict]:
        cursor = (
            self.collection.find(
                {"folder_id": folder_id, "folder_path": folder_path},
                {
                    "_id": 0,
                    "chat_id": 1,
                    "title": 1,
                    "messages": {"$slice": -1},
                    "created_at": 1,
                    "updated_at": 1,
                },
            )
            .sort("updated_at", DESCENDING)
            .limit(limit)
        )
        return list(cursor)

    def get_chat(self, chat_id: str, folder_id: str, folder_path: str) -> dict | None:
        return self.collection.find_one(
            {"chat_id": chat_id, "folder_id": folder_id, "folder_path": folder_path},
            {"_id": 0},
        )

    def create_chat(
        self,
        folder_id: str,
        folder_path: str,
        user_message: dict,
        assistant_message: dict,
    ) -> str:
        now = utc_now()
        chat_id = uuid.uuid4().hex
        self.collection.insert_one(
            {
                "chat_id": chat_id,
                "folder_id": folder_id,
                "folder_path": folder_path,
                "title": make_chat_title(user_message["content"]),
                "messages": [user_message, assistant_message],
                "created_at": now,
                "updated_at": now,
            }
        )
        return chat_id

    def append_exchange(
        self,
        chat_id: str,
        folder_id: str,
        folder_path: str,
        user_message: dict,
        assistant_message: dict,
    ) -> None:
        self.collection.update_one(
            {"chat_id": chat_id, "folder_id": folder_id, "folder_path": folder_path},
            {
                "$push": {"messages": {"$each": [user_message, assistant_message]}},
                "$set": {"updated_at": utc_now()},
            },
        )

    def delete_chat(self, chat_id: str, folder_id: str, folder_path: str) -> int:
        result = self.collection.delete_one(
            {"chat_id": chat_id, "folder_id": folder_id, "folder_path": folder_path}
        )
        return result.deleted_count
