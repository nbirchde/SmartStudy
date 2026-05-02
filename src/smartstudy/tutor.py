from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

# Instructions for the tutor chain.
_SYSTEM = """\
You are a Formal Academic Tutor helping a university student prepare for exams.

Your rules:
1. Answer ONLY using the lecture notes provided in the context. Do not use outside knowledge.
2. Cite every claim with its source using the format [File: <source_file>, Page <page>].
3. Structure your answer clearly — use bullet points or numbered steps when appropriate.
4. End EVERY response with exactly one pedagogical follow-up question to check the student's understanding.
5. If the context does not contain the answer, respond exactly:
   "This topic does not appear in the uploaded lecture notes. \
Please upload the relevant PDF and try again."

Be precise, concise, and encouraging.\
"""


def _format_docs(docs: list[Document]) -> str:
    parts = []
    for doc in docs:
        source = doc.metadata.get("source_file", "unknown")
        page = doc.metadata.get("page", "?")
        parts.append(f"[File: {source}, Page {page}]\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)


def build_chain(retriever, project: str, location: str, model_name: str):
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        project=project,
        location=location,
        temperature=0.3,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        ("human", "Lecture notes (context):\n\n{context}\n\nStudent question: {question}"),
    ])

    chain = (
        {
            "context": retriever | _format_docs,
            "question": RunnablePassthrough(),
        }
        | prompt
        | llm
        | StrOutputParser()
    )

    return chain
