import scraper
import reader
import writer
import os
import json

states_list = ["AL", "AZ", "CA", "CO", "DC", "DE", "IA", "IN", "KS", "MD", "ME", "MO", "NY", "OK", "OR", "SC", "TX", "UT", "VA", "VT", "WI"]

# new_scraper = scraper.Scraper()
# new_scraper.scrape_all()

new_reader = reader.Reader()

for state in states_list:
    this_dict = new_reader.csv_to_dict(os.path.expanduser('~') + '/.warn-scraper/exports/' + state.lower() + '.csv', state.lower())
    new_reader.write_to_disk(json.dumps(this_dict), state.lower())

new_reader.update_companies()