from db.chroma_client import collection
import time

# ============================================================
# CACHE CONFIG
# ============================================================

search_cache = {}
CACHE_TTL = 3000  # 5 minutes


def normalize_query(query):
    return query.lower().strip()


def get_cache(key):
    entry = search_cache.get(key)

    if not entry:
        return None

    # ✅ Expiry check
    if time.time() - entry["time"] > CACHE_TTL:
        del search_cache[key]
        return None

    return entry["data"]


def set_cache(key, value):
    search_cache[key] = {"data": value, "time": time.time()}


# ============================================================
# VECTOR SEARCH
# ============================================================


def vector_search(query, n_results=20):
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    output = []

    for i in range(len(results["documents"][0])):
        output.append(
            {
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "score": results["distances"][0][i],
            }
        )

    return output


# ============================================================
# NORMALIZATION
# ============================================================


def normalize_scores(results):
    for r in results:
        r["score"] = 1 / (1 + r["score"])
    return results


# ============================================================
# KEYWORD BOOST
# ============================================================


def keyword_boost(query, results):
    query_words = query.lower().split()

    for r in results:
        text = r["document"].lower()
        matches = sum(1 for word in query_words if word in text)
        r["score"] += matches * 0.05

    return results


# ============================================================
# PHRASE BOOST
# ============================================================


def phrase_boost(query, results):
    query_lower = query.lower()

    for r in results:
        if query_lower in r["document"].lower():
            r["score"] += 0.2

    return results


# ============================================================
# DEDUPLICATE
# ============================================================


def deduplicate(results):
    seen = set()
    unique = []

    for r in results:
        key = (r["metadata"]["file_name"], r["metadata"]["chunk_id"])

        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


# ============================================================
# LIMIT PER FILE
# ============================================================


def limit_per_file(results, limit=2):
    file_count = {}
    final = []

    for r in results:
        file = r["metadata"].get("file_name")

        if file_count.get(file, 0) < limit:
            final.append(r)
            file_count[file] = file_count.get(file, 0) + 1

    return final


# ============================================================
# SCORE FILTER
# ============================================================


def filter_by_score(results, min_score=0.6):
    filtered = [r for r in results if r["score"] >= min_score]
    return filtered if filtered else results


# ============================================================
# HYBRID SEARCH WITH CACHE
# ============================================================


def hybrid_search(query, top_k=5, domain=None, brand=None):

    # ✅ Normalize query
    normalized_query = normalize_query(query)
    cache_key = f"{normalized_query}_{top_k}"

    # ✅ Check cache
    cached_result = get_cache(cache_key)
    if cached_result:
        print("✅ Cache HIT")
        return cached_result

    print("❌ Cache MISS → computing...")

    # ✅ Step 1
    results = vector_search(query, n_results=top_k * 4)

    if not results:
        return []

    # ✅ Step 2
    results = normalize_scores(results)

    # ✅ Step 3
    results = keyword_boost(query, results)

    # ✅ Step 4
    results = phrase_boost(query, results)

    # ✅ Step 5
    results = deduplicate(results)

    # ✅ Step 6
    results = limit_per_file(results, limit=2)

    # ✅ Step 7
    results = filter_by_score(results, min_score=0.6)

    # ✅ Step 8
    results.sort(key=lambda x: x["score"], reverse=True)

    # ✅ Step 9
    results = results[:top_k]

    # ✅ Step 10
    output = []

    for r in results:
        output.append(
            {
                "answer": r["document"].strip(),
                "file": r["metadata"].get("file_name"),
                "category": r["metadata"].get("category"),
                "score": round(r["score"], 4),
                "chunk_id": r["metadata"].get("chunk_id"),
            }
        )

    # ✅ Store in cache
    set_cache(cache_key, output)

    return output


# ============================================================
# CLEAR CACHE (CALL AFTER INDEXING)
# ============================================================


def clear_search_cache():
    search_cache.clear()
    print("🧹 Cache cleared")
