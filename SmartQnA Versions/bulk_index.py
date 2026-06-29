@app.post("/bulk-index")
async def bulk_index():
    """
    Scan the entire Data/ folder and index all files into ChromaDB.
    Use this to index pre-existing datasets that were placed directly
    in Data/ without going through the upload UI.
    Skips files already indexed (checks chunk IDs before inserting).
    """
    import os
    from pathlib import Path
    from services.metadata_service import generate_metadata_for_file
    from services.indexing_service import index_single_file

    data_folder   = Path("Data").resolve()
    supported_ext = {".csv", ".pdf", ".html", ".mhtml", ".mht", ".json"}

    total_files  = 0
    total_chunks = 0
    skipped      = 0
    errors       = []

    logger.info("Bulk index started — scanning Data/ folder")

    for file_path in data_folder.rglob("*"):
        if file_path.is_dir():
            continue
        if file_path.suffix.lower() not in supported_ext:
            continue

        total_files += 1
        logger.info(f"Processing: {file_path.name}")

        try:
            # Generate metadata (skips if already exists)
            result = generate_metadata_for_file(
                str(file_path), data_folder="Data"
            )

            # Index the file (skips duplicate chunks automatically)
            chunks = index_single_file(str(file_path), data_folder="Data")
            total_chunks += chunks

            if result["skipped"]:
                skipped += 1

        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}")
            errors.append({"file": file_path.name, "error": str(e)})

    clear_search_cache()

    logger.info(
        f"Bulk index complete | files: {total_files} | "
        f"chunks: {total_chunks} | skipped: {skipped}"
    )

    return {
        "status":       "complete",
        "files_found":  total_files,
        "chunks_indexed": total_chunks,
        "skipped":      skipped,
        "errors":       errors,
    }

# Alias for backward compatibility
@app.post("/index")
async def index_alias():
    return await bulk_index()
