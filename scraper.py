import os

class Scraper: 
    def scrape_all(self):
        os.system("cd /Users/jon/git/warn_reporter/warn-scraper && /usr/local/bin/pipenv run python -m warn.cli AL AK AZ CA CO CT DC DE FL IA IN KS MD ME MO NY OK OR SC TX UT VA VT WI")
        

# new_scraper = Scraper()
# new_scraper.scrape_all()
