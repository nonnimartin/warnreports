from fastapi import FastAPI
import writer

app = FastAPI()

@app.get("/all_companies")
def read_root():
    this_writer = writer.Writer()
    return this_writer.get_all_companies()