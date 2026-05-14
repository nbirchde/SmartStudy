from src.smartstudy.chats import ChatStore, make_chat_message, make_chat_title


class FakeDeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, key, direction):
        reverse = direction < 0
        self.documents = sorted(self.documents, key=lambda item: item[key], reverse=reverse)
        return self

    def limit(self, limit):
        self.documents = self.documents[:limit]
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeCollection:
    def __init__(self):
        self.documents = []
        self.indexes = []

    def create_index(self, spec, unique=False):
        self.indexes.append((spec, unique))

    def insert_one(self, document):
        self.documents.append(document)

    def find(self, query, projection):
        found = []
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                copy = {key: document[key] for key in document if key != "_id"}
                if projection.get("messages", {}).get("$slice") == -1:
                    copy["messages"] = document["messages"][-1:]
                found.append(copy)
        return FakeCursor(found)

    def find_one(self, query, projection):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return {key: document[key] for key in document if key != "_id"}
        return None

    def update_one(self, query, update):
        document = self.find_one(query, {"_id": 0})
        if not document:
            return
        original = next(item for item in self.documents if item["chat_id"] == document["chat_id"])
        original["messages"].extend(update["$push"]["messages"]["$each"])
        original.update(update["$set"])

    def delete_one(self, query):
        before = len(self.documents)
        self.documents = [
            document
            for document in self.documents
            if not all(document.get(key) == value for key, value in query.items())
        ]
        return FakeDeleteResult(before - len(self.documents))


def test_make_chat_title_trims_whitespace_and_length():
    assert make_chat_title("   hello   there   ") == "hello there"
    assert len(make_chat_title("x" * 100)) == 60


def test_chat_store_create_list_append_and_delete():
    collection = FakeCollection()
    store = ChatStore(collection)
    store.ensure_indexes()

    user = make_chat_message("user", "Explain the first lecture")
    assistant = make_chat_message("assistant", "Upload notes first.")
    chat_id = store.create_chat("folder-1", "main", user, assistant)

    chats = store.list_chats("folder-1", "main")
    assert [chat["chat_id"] for chat in chats] == [chat_id]
    assert chats[0]["title"] == "Explain the first lecture"
    assert len(chats[0]["messages"]) == 1

    next_user = make_chat_message("user", "What should I upload?")
    next_assistant = make_chat_message("assistant", "Start with PDFs.")
    store.append_exchange(chat_id, "folder-1", "main", next_user, next_assistant)

    full_chat = store.get_chat(chat_id, "folder-1", "main")
    assert [message["role"] for message in full_chat["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]

    assert store.delete_chat(chat_id, "folder-1", "main") == 1
    assert store.list_chats("folder-1", "main") == []


def test_chat_store_filters_by_workspace():
    collection = FakeCollection()
    store = ChatStore(collection)

    store.create_chat("folder-1", "main", make_chat_message("user", "main"), make_chat_message("assistant", "a"))
    store.create_chat("folder-1", "other", make_chat_message("user", "other"), make_chat_message("assistant", "b"))

    assert [chat["title"] for chat in store.list_chats("folder-1", "main")] == ["main"]
