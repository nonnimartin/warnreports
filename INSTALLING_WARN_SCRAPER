# my instructions

install pipenv - `pip install pipenv`

install dependencies in warn_reporter dir (not scraper) - `pipenv install`

run make - `make ./warn-scraper/Makefile` in proj directory

pip install fastapi

pip install pydantic

to run the script, for example for AK, `pipenv run python -m warn.cli AK`

pip install feedgenerator

pip install boto3
-----
run on all - 
`pipenv run python -m warn.cli --log-level DEBUG all`

-----

states having trouble:

GA due to http://www.dol.state.ga.us/public/es/warn/searchwarns/list?geoArea=9&year=2023&step=search 404ing

WI also not working due to `/retry.py", line 592, in increment
    raise MaxRetryError(_pool, url, error or ResponseError(cause))
urllib3.exceptions.MaxRetryError: HTTPSConnectionPool(host='dwd.wisconsin.gov', port=443): Max retries exceeded with url: /dislocatedworker/warn/ (Caused by NewConnectionError('<urllib3.connection.HTTPSConnection object at 0x7f8a61021160>: Failed to establish a new connection: [Errno 8] nodename nor servname provided, or not known'))`



-----

`pipenv run python -m warn.cli --log-level DEBUG AL AZ CA CO DC DE IA IN KS MD ME MO NY OK OR SC TX UT VA VT`



