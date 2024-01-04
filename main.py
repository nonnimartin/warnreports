from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
import writer
import reader

app = FastAPI()

class Data(BaseModel):
    email: str
    company: str

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

@app.post("/make_contact")
async def make_contact(data: Data):
    
    this_writer = writer.Writer()
    # only try to write to db if user doesn't exist with the same email and company
    if this_writer.is_duplicate_user(data.email, data.company):
        raise HTTPException(status_code=409, detail="409 Conflict: Duplicate User")
    
    if not data:
         raise HTTPException(status_code=400, detail="400 Bad Request")
    
    if len(data.company) == 0 or len(data.email) == 0:
         raise HTTPException(status_code=400, detail="400 Bad Request")
    else:
        this_writer = writer.Writer()
        this_reader = reader.Reader()
        this_config = reader.Reader.get_config()
        this_writer.make_contact(data.email, data.company)
        this_subject = 'WARN Notices - Confirm Your Account'
        this_token = this_writer.get_token_for_user(data.email)
        this_body = 'Hi!<br><br>To confirm your account, please <a href=' + this_config['hostname'] + '/confirm?token=' + this_token + '&email=' + data.email + '>click on this link</a>.'
        this_reader.send_email(this_config['email_account'], data.email, this_subject, this_body)
        
        return data
    
@app.get("/get_companies_like/{this_str}")
# make this secure
async def get_companies_like(this_str: str):
    if not this_str:
         raise HTTPException(status_code=400, detail="400 Bad Request")
    else:
        this_writer = writer.Writer()
        return this_writer.get_companies_like(this_str)

@app.get("/unsubscribe")
async def unsubscribe(email: str, token: str):
    this_writer = writer.Writer()

    if not this_writer.validate_token(email, token):
         raise HTTPException(status_code=401, detail="401 Unauthorized") 
    if not (email and token):
         raise HTTPException(status_code=400, detail="400 Bad Request")
    else:
        this_writer = writer.Writer()
        return this_writer.unsubscribe(email)

@app.get("/confirm")
async def confirm(email: str, token: str):
    this_writer = writer.Writer()

    if not this_writer.validate_token(email, token):
         print("email: " + email)
         print("token: " + token)
         
         raise HTTPException(status_code=401, detail="401 Unauthorized") 
    if not (email and token):
         raise HTTPException(status_code=400, detail="400 Bad Request")
    else:
        this_writer = writer.Writer()
        return this_writer.confirm(email)


app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/scripts", StaticFiles(directory="scripts"), name="scripts")