from collections import defaultdict
from datetime import datetime, timezone
import threading

import re

#{ip : [timestamp, timestamp, ...]}
_request_log: dict = defaultdict(list)
_lock = threading.Lock()

RATE_LIMIT = 10 #max request
WINDOW_SECONDS = 60 # per this many seconds

# guardrail 1 - Rate Limiting
def check_rate_limit(client_ip:str) -> tuple[bool, str | None]:
    now = datetime.now(timezone.utc).timestamp()

    with _lock:
        # drop timestamp outside the window
        _request_log[client_ip] = [t for t in _request_log[client_ip] if now - t < WINDOW_SECONDS]

        if len(_request_log[client_ip]) >= RATE_LIMIT:
            return False, f"rate limit exceeded: {RATE_LIMIT} request per {WINDOW_SECONDS}s"
        
        _request_log[client_ip].append(now)
        return True, None


# guardrail 2 - PII Redaction
PII_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), "[REDACTED_EMAIL]"),
    (re.compile(r'\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'), "[REDACTED_PHONE]"),
]

def redact_pii(text: str) -> tuple[bool, str ]:
    redacted = text
    found = False
    for patter, replacement in PII_PATTERNS:
        new_text = patter.sub(replacement, redacted)

        if new_text != redacted:
            found = True
        redacted = new_text
    return redacted, found # returns (redacted_text, was_pii_found)


# guardrail 3 - Injection Detection
INJECTION_PATTERNS = [
    re.compile(r'ignore\s+(all\s+)?(previous|prior|above)\s+instructions?', re.IGNORECASE),
    re.compile(r'reveal\s+(your\s+)?(system\s+prompt|instructions?|prompt)', re.IGNORECASE),
    re.compile(r'you\s+are\s+now\s+', re.IGNORECASE),
    re.compile(r'forget\s+(everything|all|your)', re.IGNORECASE),
    re.compile(r'act\s+as\s+(if\s+you\s+are|a\s+)', re.IGNORECASE),
    re.compile(r'do\s+not\s+follow', re.IGNORECASE),
    # allow up to 3 intervening words so "override your safety rules" and
    # "disregard your prior instructions" are both caught
    re.compile(r'(disregard|bypass|override)\s+(\w+\s+){0,3}(instructions?|rules?|guidelines?|safety)', re.IGNORECASE),
]

def check_injection(text: str) -> tuple[bool, str | None]:
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return False, f"prompt injection pattern detected: '{pattern.pattern}'"
        
    return True, None # returns (allowed: bool, reason: str | None)
    

# Query normalization — maps user-facing synonyms to the terminology used in
# the knowledge base documents, so a small LLM doesn't have to do synonym reasoning.
_SYNONYM_MAP = [
    (re.compile(r'\bvacation\s+days?\b', re.IGNORECASE), "annual leave"),
    (re.compile(r'\bpaid\s+time\s+off\b', re.IGNORECASE), "annual leave"),
    (re.compile(r'\bPTO\b'), "annual leave"),
    (re.compile(r'\bsick\s+days?\b', re.IGNORECASE), "sick leave"),
    (re.compile(r'\bmaternity\s+leave\b', re.IGNORECASE), "parental leave"),
    (re.compile(r'\bpaternity\s+leave\b', re.IGNORECASE), "parental leave"),
]

def normalize_query(text: str) -> str:
    for pattern, replacement in _SYNONYM_MAP:
        text = pattern.sub(replacement, text)
    return text


# guardrail 4 - Output Filtering
DENYLIST = [
    re.compile(r'\bpassword\b', re.IGNORECASE),
    re.compile(r'\bsecret\b', re.IGNORECASE),
    re.compile(r'\bapi[_\s]?key\b', re.IGNORECASE),
    re.compile(r'\btoken\b', re.IGNORECASE),
]

def filter_output(text: str) -> tuple[bool, str | None]:
    # check PII in output
    for pattern, label in PII_PATTERNS:
        if pattern.search(text):
            return False, f"output contains PII: {label}"
    # check denylist
    for pattern in DENYLIST:
        if pattern.search(text):
            return False, f"output contains sensitive keyword: '{pattern.pattern}'"
    return True, None