import scraper
import reader
import writer
import os

states_list = ["AL", "AK", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "HI", "IA", "IN", "KS", "MD", "ME", "MO", "NY", "OK", "OR", "SC", "TX", "UT", "VA", "VT", "WI"]

new_scraper = scraper.Scraper()

for state in states_list:
    try:
        new_scraper.scrape_by_state(state)
    except:
        continue

new_reader = reader.Reader()
new_writer = writer.Writer()
for state in states_list:
    print(state)
    this_dict = new_reader.csv_to_dict(os.path.expanduser('~') + '/.warn-scraper/exports/' + state.lower() + '.csv', state.lower())
    new_reader.write_to_disk(this_dict, state.lower())

new_reader.update_companies()
new_reader.send_out_reports()
exit()


