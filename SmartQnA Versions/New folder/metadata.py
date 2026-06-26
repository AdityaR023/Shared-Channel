import os
import json
from pathlib import Path
 
import pandas as pd
 
# Optional PDF support
try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# creating map
file_mapping={}

# ============================================================
# BASIC FILE INFO
# ============================================================
 
def get_basic_metadata(file_path):
    return {
        "file_name": os.path.basename(file_path),
        "relative_path": str(file_path),
        "extension": Path(file_path).suffix.lower()
    }
 

def create_metadata_json(file_path, metadata):
    base_output_dir = "metadata"

    absolute_path = Path(file_path).resolve()
    base_data_path = Path("data").resolve()

    relative_path = absolute_path.relative_to(base_data_path)

    output_dir = os.path.join(base_output_dir, str(relative_path.parent))
    os.makedirs(output_dir, exist_ok=True)

    file_name = relative_path.stem
    output_file = os.path.join(output_dir, f"{file_name}_metadata.json")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)

    # mapping uses RELATIVE path (clean)
    
    # SHORT → SHORT mapping
    metadata_relative_path = str(Path(output_dir) / f"{file_name}_metadata.json")

    file_mapping[str(relative_path)] = metadata_relative_path

# ============================================================
# CSV SCHEMA
# ============================================================
 
def extract_csv_schema(file_path):
    try:
        df = pd.read_csv(file_path)

        result = {
            "file_name":Path(file_path).stem,
            "type": "csv",
            "row_count": len(df),                 
            "column_count": len(df.columns),      
            "columns": [
                {
                    "name": col,
                    "datatype": str(df[col].dtype),
                    "non_null_count": int(df[col].count())   
                }
                for col in df.columns
            ]
        }
        create_metadata_json(file_path,result)
    except Exception as e:
        return {
            "type": "csv",
            "error": str(e)
        }
def infer_json_schema(data):
    if isinstance(data, dict):
        return {
            key: infer_json_schema(value)
            for key, value in data.items()
        }

    elif isinstance(data, list):
        if len(data) > 0:
            return [infer_json_schema(data[0])]  # sample first item
        else:
            return []

    else:
        return type(data).__name__
    
def extract_json_schema(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # record count logic
        if isinstance(data, list):
            record_count = len(data)
        elif isinstance(data, dict):
            record_count = 1
        else:
            record_count = 0

        metadata = {
            "file_name": Path(file_path).stem,
            "type": "json",
            "record_count": record_count,
            "structure_type": type(data).__name__,  
            "schema": infer_json_schema(data)
        }

        # create metadata file
        create_metadata_json(file_path, metadata)

    except Exception as e:
        metadata = {
            "file_name": Path(file_path).stem,
            "type": "json",
            "error": str(e)
        }
def extract_mhtml_schema(file_path):
 
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(5000)
 
        result = {
            "file_name":Path(file_path).stem,
            "type": "mhtml",
            "contains_html": "<html" in content.lower(),
            "contains_tables": "<table" in content.lower(),
            "contains_images": "image/" in content.lower()
        }
        create_metadata_json(file_path,result)
    except Exception as e:
        return {
            "type": "mhtml",
            "error": str(e)
        }
 
# ============================================================
# PDF METADATA
# ============================================================
def extract_pdf_metadata(file_path):
    if not PDF_SUPPORT:
        print(f"PDF support not available (PyPDF2 missing): {file_path}")
        return
 
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
 
            metadata = reader.metadata
 
            result = {
                "file_name": Path(file_path).stem,
                "type": "pdf",
                "page_count": len(reader.pages),
                "document_info": {
                    "title": metadata.title if metadata and metadata.title else None,
                    "author": metadata.author if metadata and metadata.author else None,
                    "creator": metadata.creator if metadata and metadata.creator else None,
                    "producer": metadata.producer if metadata and metadata.producer else None,
                    "subject": metadata.subject if metadata and metadata.subject else None
                }
            }
 
            create_metadata_json(file_path, result)
 
    except Exception as e:
        metadata = {
            "file_name": Path(file_path).stem,
            "type": "pdf",
            "error": str(e)
        }
        create_metadata_json(file_path, metadata)
                   
def main():
    data_folder = "Data"
    mapping_file = "file_mapping.json"

    # Load mapping
    if os.path.exists(mapping_file):
        with open(mapping_file, "r") as f:
            file_mapping.update(json.load(f))

    for root, dirs, files in os.walk(data_folder):
        for file in files:

            absolute_path = Path(os.path.join(root, file)).resolve()

            # clean relative path for mapping
            relative_path = str(absolute_path.relative_to(Path(data_folder).resolve()))

            # skip check on relative path
            if relative_path in file_mapping:
                continue
            
            ext = Path(file).suffix.lower()

            # pass absolute path for processing
            if ext == ".csv":
                extract_csv_schema(str(absolute_path))
            elif ext == ".json":
                extract_json_schema(str(absolute_path))
            elif ext in [".mhtml", ".mht", ".html"]:
                extract_mhtml_schema(str(absolute_path))
            elif ext == ".pdf":
                extract_pdf_metadata(str(absolute_path))
            else:
                print(f"Skipped unsupported file: {relative_path}")

    # Save mapping
    with open(mapping_file, "w") as f:
        json.dump(file_mapping, f, indent=4)

    print("✅ All metadata files created!")

if __name__ == "__main__":
    main()
