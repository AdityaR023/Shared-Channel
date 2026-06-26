import json
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from db.chroma_client import collection, client
from utils.extractor import extract_text
from utils.classifier import detect_category


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
def index_data(file_path, mapping_file="file_mapping.json", data_folder="Data"):

    # ✅ Load mapping
    try:
        with open(mapping_file, "r", encoding="utf-8") as f:
            file_mapping = json.load(f)
    except Exception as e:
        print("Mapping file not found:", e)
        return 0

    total_chunks = 0

    file_path = Path(file_path).resolve()
    data_folder = Path(data_folder).resolve()

    # ✅ Get relative path (same as mapping key)
    try:
        rel_path = str(file_path.relative_to(data_folder))

        # ✅ IMPORTANT: Match mapping format (\ vs /)
        rel_path = rel_path.replace("/", "\\")

    except Exception as e:
        print(f"File not inside Data folder: {file_path}")
        return 0

    # ✅ Get metadata path from mapping
    meta_path = file_mapping.get(rel_path)

    if not meta_path:
        print(f"No metadata found for: {rel_path}")
        return 0

    # ✅ Normalize metadata path for safe file reading
    meta_path = meta_path.replace("\\", "/")

    print(f"Indexing: {file_path}")
    print(f"Metadata path: {meta_path}")

    # ✅ Load metadata
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except Exception as e:
        print(f"Error reading metadata: {meta_path}, {e}")
        metadata = {}

    # ✅ Extract text
    try:
        content = extract_text(file_path)
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
        return 0

    if not content:
        print("No content extracted")
        return 0

    # ✅ Clean text
    content = clean_text(content)

    if len(content) < 50:
        print("Content too small, skipping")
        return 0

    # ✅ Format markdown
    content = format_markdown(content)

    # ✅ Detect category
    category = detect_category(file_path, metadata)

    # ✅ Chunk
    chunks = split_text(content)

    # ✅ Batch insert
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
                "file_type": file_path.suffix.lower(),
                "file_name": file_path.name,
                "file_path": str(file_path),
                "chunk_id": chunk_index
            })

        # ✅ Store batch in DB
        try:
            collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
        except Exception as e:
            print(f"Error inserting batch: {e}")
            continue

        total_chunks += len(ids)

    print(f"✅ Finished indexing: {file_path}")
    print(f"✅ Total indexed chunks: {total_chunks}")

    return total_chunks
