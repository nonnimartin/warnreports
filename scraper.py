import os

class Scraper: 
    def scrape_all():
        os.system("cd ./warn-scraper && pipenv run python -m warn.cli AL AZ CA CO DC DE IA IN KS MD ME MO NY OK OR SC TX UT VA VT WI")
        

new_scraper = Scraper
new_scraper.scrape_all()
