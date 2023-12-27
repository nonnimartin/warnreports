# warn_reporter
Create config.json file "{"email_account":"<SENDER_EMAIL>"}"
Create seed file in base dir with json {"seed":"<YOURSEED>"}
Requires the following to be installed as below:

`pip install fastapi`

`pip install "uvicorn[standard]"`

`pip install feedgen `

`pip install python-dateutil`

To run service:

`uvicorn main:app --reload`



