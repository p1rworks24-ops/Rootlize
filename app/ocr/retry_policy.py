from __future__ import annotations
from datetime import datetime,timedelta,timezone

MAX_RETRIES=3
RETRY_DELAYS=(30,300)
INCREMENT_RETRY_ERRORS=frozenset({"ocr_failed","timeout","worker_crashed","worker_unresponsive","image_decode_failed"})
TERMINAL_ERRORS=frozenset({"file_not_png","image_too_large","model_missing","model_load_failed","unsupported_protocol","invalid_request"})

def next_retry_time(retry_count_after_failure:int, now:str)->str|None:
    if retry_count_after_failure>=MAX_RETRIES: return None
    base=datetime.fromisoformat(now)
    delay=RETRY_DELAYS[min(retry_count_after_failure-1,len(RETRY_DELAYS)-1)]
    return (base+timedelta(seconds=delay)).astimezone(timezone.utc).isoformat()
