import os
import re

import numpy as np
import requests

OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


# INSTRUCTION SCAN
INSTRUCTION_PATTERNS = [
    re.compile(r'ignore\s+(all\s+)?(previous|prior|above)\s+instructions?', re.IGNORECASE),
    re.compile(r'you\s+are\s+now\s+', re.IGNORECASE),
    re.compile(r'forget\s+(everything|all|your)', re.IGNORECASE),
    re.compile(r'(disregard|bypass|override)\s+(your\s+)?(instructions?|rules?|guidelines?)', re.IGNORECASE),
    re.compile(r'call\s+(the\s+)?(flag|flag_document)\s+tool', re.IGNORECASE),
    re.compile(r'reveal\s+(your\s+)?(system\s+)?prompt', re.IGNORECASE),
]

def scan_instructions(text : str) -> tuple[bool, str | None]:
    for pattern in INSTRUCTION_PATTERNS:
        if pattern.search(text):
            return False, f"instruction pattern detected : '{pattern.pattern}'"
    return True, None # returns (clean: bool, reason: str | None)


# EMBEDDING OUTLIER SCORE
FLAG_THRESHOLD = 0.5 #flag if cosine distance exceeds this
REJECT_THRESHOLD = 0.8 # reject if cosine distance exceeds thsi

def embed(text : str) -> list[float]:
    response = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": text}
    )
    return response.json()["embedding"]

def cosine_distance(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return 1.0 - float(np.dot(a,b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def get_corpus_centroid(collection) -> list[float] | None:
    # returns None if collection is empty (first doc always accepted)
    result = collection.get(include=["embeddings"])
    if len(result["embeddings"]) == 0:
        return None
    return np.mean(result["embeddings"], axis=0).tolist()

def check_outlier(doc_embedding : list[float], collection) -> tuple[float, str]:
    centroid = get_corpus_centroid(collection)
    if centroid is None:
        return 0.0, "accept" #empty corpus - first doc is always accepted
    distance = cosine_distance(doc_embedding, centroid)
    if distance > REJECT_THRESHOLD:
        return distance, "reject"
    if distance > FLAG_THRESHOLD:
        return distance, "flag"
    return distance, "accept"

# SOURCE TRUST SCORE
# Provenance tiers and their threshold multipliers
TRUST_MULTIPLIER = {
    "verified" : 1.0, #use default thresholds
    "user_submitted" : 0.7, # flag/reject at 70% of default distance
}

def apply_trust(distance: float, provenance: str) -> tuple[float, str]:
    multiplier = TRUST_MULTIPLIER.get(provenance, 0.7) # unknown provenanve -> treat as user_submitted
    adjusted_flag = FLAG_THRESHOLD * multiplier
    adjusted_reject = REJECT_THRESHOLD * multiplier
    if distance > adjusted_reject:
        return distance, "reject"
    if distance > adjusted_flag:
        return distance, "flag"
    return distance, "accept"


# Combining Three Checks
def assess_document(content : str, provenance: str, collection) -> dict:
    #1. instrction scan (cheap, always first)
    clean , reason = scan_instructions(content)
    if not clean:
        return {"decision": "reject", "reason": reason, "outlier_distance" :  None}
    

    #2. embed
    doc_embedding = embed(content)

    # 3. outlier score with trust adjustment
    distance, decision = apply_trust(
        cosine_distance(doc_embedding, get_corpus_centroid(collection) or doc_embedding), 
        provenance
    )

    return {
        "decision" : decision,
        "reason" : f"outlier distance={distance:.3f},provenance={provenance}",
        "outlier_distance" : round(distance, 4),
        "embedding": doc_embedding,  # pass through so gateway can add with correct dimensions
    }


