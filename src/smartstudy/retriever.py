from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from pymongo import MongoClient

# Build a retriever that fetches relevant lecture chunks from MongoDB Atlas based on the student's question.
def build_retriever(
    mongo_uri: str,
    database: str,
    collection_name: str,
    index_name: str,
    project: str,
    location: str,
    embedding_model: str,
    k: int = 5,
):
    embeddings = GoogleGenerativeAIEmbeddings(
        model=embedding_model,
        project=project,
        location=location,
    )

    client = MongoClient(mongo_uri)
    collection = client[database][collection_name]

    vector_store = MongoDBAtlasVectorSearch(
        collection=collection,
        embedding=embeddings,
        index_name=index_name,
        text_key="text",
        embedding_key="embedding",
    )

    return vector_store.as_retriever(search_kwargs={"k": k})
