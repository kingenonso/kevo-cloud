from fastapi import FastAPI

app = FastAPI(title="KEVO API")


@app.get("/")
def home():
    return {"message": "Welcome to KEVO API"}