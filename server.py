import os
from mcp.server.fastmcp import FastMCP
from langchain_chroma import Chroma
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from PyPDF2 import PdfReader

# Initialize the FastMCP server
mcp = FastMCP("Chroma-RAG-Server")

# Initialize ChromaDB with HuggingFace embeddings
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_store = Chroma(
    collection_name="mcp_pdf_collection",
    embedding_function=embeddings,
    persist_directory="E:/RAG Chatbot/chroma_db_data"
)

@mcp.tool()
def process_pdf(file_path: str, user_id: str) -> str:
    """Extracts text from a PDF, chunks it, and saves it to CxhromaDB."""
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        text = ""
        file_name = os.path.basename(file_path)
        pdf_reader = PdfReader(file_path)
        for page in pdf_reader.pages:
            text += page.extract_text()

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = text_splitter.split_text(text)

        # Attach user_id metadata for multi-tenant isolation
        metadatas = [{"user_id": user_id, "source": file_name} for _ in chunks]
        vector_store.add_texts(texts=chunks, metadatas=metadatas)
        
        return f"Success! Processed {len(chunks)} chunks."
    except Exception as e:
        return f"Error processing PDF: {str(e)}"

@mcp.tool()
def search_pdfs(query: str, user_id: str) -> str:
    """Searches ChromaDB for user-specific documents and includes metadata."""
    try:
        results = vector_store.similarity_search(query, k=4, filter={"user_id": user_id})
        
        if not results:
            return "No relevant context found in your documents."
            
        # Extract the text AND the filename for explainability
        formatted_chunks = []
        for doc in results:
            # Get the filename from the source path we saved earlier
            source_file = os.path.basename(doc.metadata.get("source", "Unknown Document"))
            chunk_text = doc.page_content
            
            # Format it clearly so the LLM and the user can read it
            formatted_chunks.append(f"--- SOURCE: {source_file} ---\n{chunk_text}\n")
            
        return "\n\n".join(formatted_chunks)
        
    except Exception as e:
        return f"Error searching database: {str(e)}"

@mcp.tool()
def delete_pdf(file_name: str, user_id: str) -> str:
    """Deletes a document's vector embeddings from ChromaDB instantly."""
    try:
        vector_store._collection.delete(
            where={"$and": [{"user_id": user_id}, {"source": file_name}]}
        )
        return "Successfully deleted from ChromaDB."
    except Exception as e:
        return f"Error deleting from database: {str(e)}"

@mcp.tool()
def delete_all_pdfs(user_id: str) -> str:
    """Deletes ALL document embeddings for a specific user from ChromaDB instantly."""
    try:
        # Notice we only filter by user_id here, which wipes all their files
        vector_store._collection.delete(
            where={"user_id": user_id}
        )
        return "Successfully deleted all documents from ChromaDB."
    except Exception as e:
        return f"Error deleting from database: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")