from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Triage AI Backend Running - TEST VERSION"}

@app.get("/health")
def health():
    return {"status": "healthy"}