import os

class Scraper: 
    def scrape_ak():
        os.system("cd ./warn-scraper && pipenv run python -m warn.cli --log-level DEBUG AL AZ CA CO DC DE IA IN KS MD ME MO NY OK OR SC TX UT VA VT")
        

new_scraper = Scraper
new_scraper.scrape_ak()
