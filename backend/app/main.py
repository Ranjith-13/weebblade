from fastapi import FastAPI

app = FastAPI(title="WeebBlade API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "WeebBlade API — under construction"}
