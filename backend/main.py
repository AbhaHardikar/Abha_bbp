
from fastapi import FastAPI

app = FastAPI(title="Boston Bioprocess API")


@app.get("/")
def home():
    return {
        "message": "Boston Bioprocess API is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }
