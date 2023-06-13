from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import writer

app = FastAPI()

@app.get("/all_companies")
def read_root():
    this_writer = writer.Writer()
    return this_writer.get_all_companies()

app.mount("/static", StaticFiles(directory="static"), name="static")