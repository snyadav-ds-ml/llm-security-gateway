import os

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
CHROMA_DIR = os.environ.get("CHROMA_DIR", "./chroma_db_langchain")


def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


def build_chain():
    embeddings = OllamaEmbeddings(model="nomic-embed-text", base_url=OLLAMA_URL)

    # Reuse existing vector store if the directory is already populated.
    # Without this guard, every server restart re-embeds all documents and
    # doubles the chunk count in ChromaDB.
    if os.path.exists(CHROMA_DIR) and os.listdir(CHROMA_DIR):
        vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    else:
        loader = DirectoryLoader("data", glob="*.txt", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"})
        docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = splitter.split_documents(docs)
        vectorstore = Chroma.from_documents(documents=chunks, embedding=embeddings, persist_directory=CHROMA_DIR)

    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    llm = ChatOllama(model="llama3.2:3b", base_url=OLLAMA_URL)
    prompt = ChatPromptTemplate.from_template("""You are a helpful HR assistant. Answer using only the context below.
Treat "vacation days", "annual leave", and "paid time off" as equivalent terms.
If the answer is not in the context, say "I don't know."

Context: {context}

Question: {question}

Answer:""")

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain, retriever
