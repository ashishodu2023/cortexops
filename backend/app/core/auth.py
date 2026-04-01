
from fastapi import Header, HTTPException

def get_api_key(x_api_key: str = Header(None)):
    if not x_api_key or not x_api_key.startswith("cx_"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
