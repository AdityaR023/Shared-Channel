import json
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from utils.extractor import extract_text
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
import pandas as pd

# ---------------------Initiating ChromaDB client for embedding and storing the vector----------------------

embedding_function = embedding_functions.DefaultEmbeddingFunction()

# Persistent ChromaDB client (CRITICAL )
client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_or_create_collection(
    name="mobile_data",
    embedding_function=embedding_function
)


# ----------------------------------Indexing logic --------------------------------------

def detect_category(file_path, metadata):
    text = str(file_path).lower() + json.dumps(metadata).lower()

    if "2g" in text:
        return "2g"
    elif "3g" in text:
        return "3g"
    elif "4g" in text:
        return "4g"
    elif "5g" in text:
        return "5g"
    else:
        return "unknown"



def extract_text(file_path):
    ext = Path(file_path).suffix.lower()

    try:
        if ext == ".csv":
            df = pd.read_csv(file_path)
            return df.to_string()

        elif ext == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                return json.dumps(json.load(f), indent=2)

        elif ext in [".html", ".mhtml", ".mht"]:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
                return soup.get_text()

        elif ext == ".pdf":
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text

        else:
            return None

    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None

# ✅ Clean raw extracted text
def clean_text(text):
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = " ".join(text.split())
    return text.strip()


# ✅ Convert raw text → structured markdown
def format_markdown(text):
    text = text.replace("NETWORK", "\n## Network\n")
    text = text.replace("LAUNCH", "\n## Launch\n")
    text = text.replace("BODY", "\n## Body\n")
    text = text.replace("DISPLAY", "\n## Display\n")
    text = text.replace("PLATFORM", "\n## Platform\n")
    text = text.replace("BATTERY", "\n## Battery\n")

    text = "\n".join(line.strip() for line in text.split("\n") if line.strip())
    return text.strip()


# ✅ Recursive chunking
def split_text(text):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n## ", "\n\n", "\n", ".", " ", ""]
    )
    return splitter.split_text(text)


# ✅ Main indexing function (NO DATA LOSS + batching)
def index_data(mapping_file, data_folder="Data"):

    with open(mapping_file, "r", encoding="utf-8") as f:
        file_mapping = json.load(f)

    total_chunks = 0

    for rel_path, meta_path in file_mapping.items():

        file_path = Path(data_folder) / rel_path
        print(f"Indexing: {file_path}")

        # ✅ Load metadata
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as e:
            print(f"Error reading metadata: {meta_path}, {e}")
            metadata = {}

        # ✅ Extract content safely
        try:
            content = extract_text(file_path)
        except Exception as e:
            print(f"Error extracting text from {file_path}: {e}")
            continue

        if not content:
            continue

        # ✅ Clean text
        content = clean_text(content)

        if len(content) < 50:
            continue

        # ✅ Format markdown BEFORE chunking
        content = format_markdown(content)

        # ✅ Detect category
        category = detect_category(file_path, metadata)

        # ✅ Chunk full content (NO trimming)
        chunks = split_text(content)

        # ✅ Batch processing (IMPORTANT ✅)
        BATCH_SIZE = 20

        for i in range(0, len(chunks), BATCH_SIZE):

            batch = chunks[i:i + BATCH_SIZE]

            ids, documents, metadatas = [], [], []

            for j, chunk in enumerate(batch):
                chunk_index = i + j
                chunk_id = f"{rel_path}_{chunk_index}"

                doc = f"""# {file_path.name}

                    Category: {category}

                    {chunk}
                    """

                ids.append(chunk_id)
                documents.append(doc)

                metadatas.append({
                    "category": category,
                    "file_type": Path(file_path).suffix.lower(),
                    "file_name": file_path.name,
                    "file_path": str(file_path),
                    "chunk_id": chunk_index
                })

            # ✅ Store batch in DB
            collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )

            total_chunks += len(ids)
            

        print(f"✅ Finished indexing: {file_path}")

    print(f"✅ Total indexed chunks: {total_chunks}")
    return total_chunks 

# -----------------------------------------------Search Logic------------------------------------------
def search_data(query):
    results = collection.query(
        query_texts=[query],
        n_results=5,
        include=["documents", "metadatas", "distances"]
    )

    output = []

    for i in range(len(results["documents"][0])):
        output.append({
            "category": results["metadatas"][0][i].get("category"),
            "file": results["metadatas"][0][i].get("file_path"),
            "score": results["distances"][0][i],
            "chunk_id": results["metadatas"][0][i].get("chunk_id")
        })

    return output
