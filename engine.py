import scraper
import reader
import writer
import os
import json

states_list = ["AL", "AK", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "IA", "IN", "KS", "MD", "ME", "MO", "NY", "OK", "OR", "SC", "TX", "UT", "VA", "VT", "WI"]

# new_scraper = scraper.Scraper()
# new_scraper.scrape_all()

new_reader = reader.Reader()
new_writer = writer.Writer()
for state in states_list:
    this_dict = new_reader.csv_to_dict(os.path.expanduser('~') + '/.warn-scraper/exports/' + state.lower() + '.csv', state.lower())
    #new_reader.write_to_disk(json.dumps(this_dict), state.lower())
    new_reader.write_to_disk(this_dict, state.lower())

new_reader.update_companies()
new_reader.send_out_reports()
exit()


