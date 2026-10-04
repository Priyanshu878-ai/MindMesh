from fastapi import FastAPI

app = FastAPI(
    title="MindMesh API",
    version="0.1.0",
    description="AI-powered codebase intelligence platform",
)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "mindmesh-api",
    }
