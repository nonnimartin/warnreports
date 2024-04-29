from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import utils
from models import Company, Contact

app = FastAPI()

class Data(BaseModel):
    email: str
    company: str

@app.get("/all_companies")
async def read_root():
    q = Company.select(Company.name, Company.state)
    return list(q.tuples())

@app.get("/get_all_states")
async def get_all_states():
    q = Company.select(Company.state).distinct()
    return [c.state for c in q]

@app.get("/get_companies_by_state/{state}")
async def get_companies_by_state(state: str):
    if not state:
        raise HTTPException(status_code=400, detail="400 Bad Request")
    q = Company.select(Company.name, Company.state)
    q = q.where(Company.state.ilike(state))
    q = q.order_by(Company.name.collate('NOCASE'))
    return list(q.tuples())

@app.post("/make_contact")
async def make_contact(data: Data):
    if not data:
        raise HTTPException(status_code=400, detail="400 Bad Request")
    if len(data.company) == 0 or len(data.email) == 0:
        raise HTTPException(status_code=400, detail="400 Bad Request")
    if Contact.get_or_none(
        Contact.email == data.email,
        Contact.company == data.company):
        raise HTTPException(status_code=409, detail="409 Conflict: Duplicate User")
    contact: Contact = Contact.create(email=data.email, company=data.company)
    contact.send_confirm_email()
    return data

@app.get("/get_companies_like/{this_str}")
async def get_companies_like(this_str: str):
    if not this_str:
        raise HTTPException(status_code=400, detail="400 Bad Request")
    q = Company.select(Company.name, Company.state)
    q = q.where(Company.name.ilike(f'%{this_str}%'))
    return list(q.tuples())

@app.get("/unsubscribe")
async def unsubscribe(email: str, token: str):
    if not (email and token):
        raise HTTPException(status_code=400, detail="400 Bad Request")
    contact = authenticate(email, token)
    if not contact:
        raise HTTPException(status_code=401, detail="401 Unauthorized")
    contact.delete_instance()
    return True

@app.get("/confirm")
async def confirm(email: str, token: str):
    if not (email and token):
        raise HTTPException(status_code=400, detail="400 Bad Request")
    contact = authenticate(email, token)
    if not contact:
        raise HTTPException(status_code=401, detail="401 Unauthorized")
    contact.confirmed = utils.now()
    contact.save()
    return True

app.mount("/static", StaticFiles(directory="static"), name="static")
# app.mount("/scripts", StaticFiles(directory="scripts"), name="scripts")

def authenticate(email: str, token: str) -> Contact|None:
    if email and token:
        return Contact.get_or_none(
            Contact.email == email,
            Contact.token == token)
