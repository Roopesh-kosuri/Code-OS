import math
import re
from pathlib import Path
from backend.app.db.database import get_connection

# Common stopwords and programming keywords to ignore during TF-IDF calculations
STOPWORDS = {
    # English stopwords
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after", "above", "below", "to", "from",
    "up", "down", "in", "out", "on", "off", "over", "under", "again", "further", "then", "once", "here",
    "there", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just", "don",
    "should", "now", "this", "that", "these", "those", "have", "has", "had", "having", "do", "does",
    "did", "doing", "be", "been", "being", "is", "are", "was", "were",
    # Common programming keywords
    "import", "from", "as", "class", "def", "async", "await", "return", "function", "const", "let", "var",
    "public", "private", "protected", "static", "final", "void", "int", "double", "float", "string",
    "boolean", "char", "if", "else", "for", "while", "do", "switch", "case", "break", "continue", "try",
    "except", "catch", "finally", "throw", "throws", "new", "this", "super", "null", "true", "false",
    "package", "interface", "extends", "implements", "export", "default"
}

TOKEN_RE = re.compile(r"[A-Za-z0-9_$]+")

def tokenize(text: str) -> list[str]:
    tokens = TOKEN_RE.findall(text.lower())
    # Split camelCase and snake_case to get better sub-word matching
    expanded_tokens = []
    for token in tokens:
        if "_" in token:
            parts = token.split("_")
            expanded_tokens.extend(parts)
        # Split camelCase
        camel_parts = re.findall(r"[a-z0-9]+|[A-Z][a-z0-9]*|[A-Z]+(?=[A-Z][a-z]|$)", token)
        if len(camel_parts) > 1:
            expanded_tokens.extend(p.lower() for p in camel_parts if p)
        expanded_tokens.append(token)
    
    return [t for t in expanded_tokens if t not in STOPWORDS and len(t) > 1]

async def semantic_search(workspace: str, query: str, limit: int = 50) -> list[dict]:
    if not query:
        return []
    
    # 1. Fetch all indexed files for the workspace from the DB
    db = await get_connection()
    try:
        rows = await db.execute_fetchall(
            "SELECT path, relative_path, language FROM repo_index_files WHERE workspace = ?",
            (workspace,)
        )
    finally:
        await db.close()
    
    if not rows:
        return []
    
    # 2. Tokenize query
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    
    # Pre-calculate query token frequencies
    query_tf = {}
    for token in query_tokens:
        query_tf[token] = query_tf.get(token, 0) + 1
        
    # 3. Read files and count frequencies
    docs = []
    df = {} # Document frequency for tokens in the query
    
    for row in rows:
        file_path = Path(row["path"])
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
            
        tokens = tokenize(content)
        if not tokens:
            continue
            
        # Count frequencies
        tf = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
            
        doc_vector = {}
        # Only compute vector components for tokens that are in the query to optimize speed
        has_overlap = False
        for token in query_tf:
            if token in tf:
                doc_vector[token] = tf[token]
                df[token] = df.get(token, 0) + 1
                has_overlap = True
                
        # Also compute doc length for cosine normalization (using all tokens for accuracy)
        # We can approximate doc length as sqrt(sum(tf^2))
        doc_len = math.sqrt(sum(freq ** 2 for freq in tf.values()))
        
        if has_overlap:
            docs.append({
                "path": row["path"],
                "relative_path": row["relative_path"],
                "language": row["language"],
                "vector": doc_vector,
                "length": doc_len
            })
            
    if not docs:
        return []
        
    # 4. Compute IDF
    num_docs = len(rows)
    idf = {}
    for token, doc_freq in df.items():
        # log(1 + N / (1 + df))
        idf[token] = math.log(1.0 + (num_docs / (1.0 + doc_freq)))
        
    # 5. Compute query TF-IDF vector length
    query_vector = {}
    for token, freq in query_tf.items():
        if token in idf:
            query_vector[token] = freq * idf[token]
    query_len = math.sqrt(sum(val ** 2 for val in query_vector.values()))
    
    if query_len == 0:
        return []
        
    # 6. Compute scores and rank
    results = []
    for doc in docs:
        dot_product = 0.0
        for token, val in query_vector.items():
            if token in doc["vector"]:
                # TF(doc) * IDF * TF(query) * IDF
                doc_tfidf = doc["vector"][token] * idf[token]
                dot_product += doc_tfidf * val
                
        if dot_product > 0 and doc["length"] > 0:
            score = dot_product / (doc["length"] * query_len)
            results.append({
                "path": doc["path"],
                "relative_path": doc["relative_path"],
                "language": doc["language"],
                "score": round(score, 4)
            })
            
    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
