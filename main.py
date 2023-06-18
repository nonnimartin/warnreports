from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import writer

app = FastAPI()

@app.get("/all_companies")
async def read_root():
    this_writer = writer.Writer()
    return this_writer.get_all_companies()

@app.get("/get_all_states")
async def get_all_states():
    this_writer = writer.Writer()
    return this_writer.get_all_states()

@app.get("/get_companies_by_state/{state}")
async def get_companies_by_state(state: str):
    if not state:
         raise HTTPException(status_code=400, detail="400 Bad Request")
    else:
        this_writer = writer.Writer()
        return this_writer.get_companies_by_state(state)

app.mount("/static", StaticFiles(directory="static"), name="static")