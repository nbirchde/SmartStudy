from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI


_SYSTEM = """\
You are a Formal Academic Tutor helping a university student prepare for exams.

Your rules:
1. Answer ONLY using the lecture notes provided in the context. Do not use outside knowledge.
2. Cite every claim with its source using the format [File: <source_file>, Page <page>].
3. Structure your answer clearly — use bullet points or numbered steps when appropriate.
4. End EVERY response with exactly one pedagogical follow-up question to check the student's understanding.
5. If no lecture-note context is available, stay conversational and useful for study planning or app-workflow questions, but do not invent lecture-specific content.
6. If the student asks a lecture-specific question and the context does not contain the answer, briefly explain that the uploaded notes for this workspace do not contain enough information and suggest uploading the relevant PDF from the left panel.

Be precise, concise, and encouraging.\
"""


def _format_docs(docs: list[Document]) -> str:
    parts = []
    for doc in docs:
        source = doc.metadata.get("source_file", "unknown")
        page = doc.metadata.get("page", "?")
        parts.append(f"[File: {source}, Page {page}]\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)


def _format_sources(docs: list[Document]) -> list[dict]:
    sources = []
    seen = set()
    for doc in docs:
        source = doc.metadata.get("source_file", "unknown")
        page = doc.metadata.get("page", "?")
        key = (source, page)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "source_file": source,
            "page": page,
            "preview": doc.page_content[:280],
        })
    return sources


def build_chain(retriever, project: str, location: str, model_name: str):
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        project=project,
        location=location,
        temperature=0.3,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        (
            "human",
            "Recent chat history:\n\n{history}\n\n"
            "Lecture notes (context):\n\n{context}\n\n"
            "Student question: {question}",
        ),
    ])

    answer_chain = prompt | llm | StrOutputParser()

    def _format_history(messages: list[dict]) -> str:
        recent = messages[-8:]
        if not recent:
            return "No prior messages in this chat."
        lines = []
        for message in recent:
            role = message.get("role", "user")
            content = str(message.get("content", "")).strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines) or "No prior messages in this chat."

    def answer_with_sources(payload) -> dict:
        if isinstance(payload, dict):
            question = str(payload.get("question", ""))
            history = payload.get("history", [])
        else:
            question = str(payload)
            history = []

        docs = retriever.invoke(question)
        answer = answer_chain.invoke({
            "context": _format_docs(docs),
            "history": _format_history(history),
            "question": question,
        })
        return {
            "answer": answer,
            "sources": _format_sources(docs),
        }

    return RunnableLambda(answer_with_sources)
