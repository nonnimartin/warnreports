import uuid
# import datetime
# import rfeed.rfeed as rf
from feedgen.feed import FeedGenerator
import json
import sqlite3
import logging

class Writer:

    # write rss data from list of WARN notice items
    feed_list = list()

    def write_rss(self, notices_dict):
        counter = 0
        # write guid for RSS object
        random =  uuid.uuid4()
        fg = FeedGenerator()
        fg.id("random")
        fg.title("WARN NOTICE")
        fg.author( {'name':'John Doe','email':'john@example.kitchen'} )
        fg.link( href='http://larskiesow.de/test.atom', rel='self' )
        fg.language('en')
        fg.description('See below items')
        for company in notices_dict.keys():


            info = notices_dict[company]
            closing_or_layoff = info["Closing or Layoff"]
            initial_reporting_date = info["Initial Report Date"]
            if "Planned Starting Date" in info:
                planned_starting_date = info["Planned Starting Date"]
            city = info["City"]
            planned_no_affected_employees = info["Planned # Affected Employees"]
            random =  uuid.uuid4()
            fe = fg.add_entry()

            fe.id("entry " + str(counter))
            counter +=1 
            fe.description(company + " - " + closing_or_layoff + " - " + "Reported: " + initial_reporting_date + " - " + "Starting: " + planned_starting_date + " - " + "City: " + city + " - " + " Employees Affected: " + planned_no_affected_employees)
            fe.title = company + " - " + closing_or_layoff + " - " + "Reported: " + initial_reporting_date + " - " + "Starting: " + planned_starting_date + " - " + "City: " + city + " - " + " Employees Affected: " + planned_no_affected_employees
            fe.link(href='http://lernfunk.de/feed')
            fe.enclosure('http://lernfunk.de/media/654321/1/file.mp3', 0, 'audio/mpeg')
            # for this_item in notices_dict[company]:
            #     print(this_item)
            #     this_item = json.loads(this_item)
            #     closing_or_layoff = this_item["Closing or Layoff"]
            #     initial_reporting_date = this_item["Initial Report Date"]
            #     planned_starting_date = this_item["Planned Starting Date"]
            #     city = this_item["City"]
            #     planned_no_affected_employees = this_item["Planned # Affected Employees"]
            #     # write guid for RSS object
            #     random =  uuid.uuid4()
            #     fe = fg.add_entry()
            #     fe.title = this_item[company + " - " + closing_or_layoff + " - " + "Reported:" + initial_reporting_date + " - " + "Starting: " + planned_starting_date + " - " + "City:" + city]
            #     #fe.description = this_item['description']
            #     #fe.id(random)
            #     fe.link(href='http://lernfunk.de/feed')
            #     fe.enclosure('http://lernfunk.de/media/654321/1/file.mp3', 0, 'audio/mpeg')
            #     # feed = rf.Feed(notices_dict[company]['title'], )
            #     #items_list.append(itemified)
            
            #print(fg.rss_file("test.xml"))
            #fg.rss_str(pretty=True)
            #fg.rss_file('/tmp/test.json')

            # list of rfeed Item objects from array in dict
            # items_list = list()
            # for this_item in notices_dict[company]['items']:
            #     #print(this_item)
            #     itemified = rf.Item(this_item['title'], 'www.google.com', this_item['description'], 'nonnimartin@gmail.com', 'warn notice', None, None, None, None)
            #     # feed = rf.Feed(notices_dict[company]['title'], )
            #     items_list.append(itemified)
            
            # print(rf.Feed(company, 'www.google.com', 'See notices below', 'en-US', None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, items_list).rss())
    

    def store_contact(self, email, company, state):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            # cur.execute('INSERT INTO contacts VALUES ("' + email + '","' + company.replace("'","\\'") + '","' + state + '");')
            cur.execute('INSERT INTO contacts VALUES (?, ?)', (email, state))
            con.commit()
        except:
            logging.exception("Error writing to contacts")

    def store_company(self, company, state):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            cur.execute('INSERT INTO companies VALUES (?, ?)', (company, state))
            con.commit()
        except:
            logging.exception("Error writing to company")

    def get_contacts_by_company(self, company, state):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            cur.execute('SELECT * from contacts where (company = ? and state = ?)', (company, state))
            rows = cur.fetchall()
            return rows
        except:
            logging.exception("Error getting contacts")

    def update_companies(self):
        states_list = ["AL", "AZ", "CA", "CO", "DC", "DE", "IA", "IN", "KS", "MD", "ME", "MO", "NY", "OK", "OR", "SC", "TX", "UT", "VA", "VT", "WI"]
        
        for state in states_list:
            f = open("./reports_json/" + state.lower() + ".json")
            parsed_dict = json.load(f)
            for this_company in parsed_dict.keys():
                this_warn = parsed_dict[this_company]
                if "Company" not in this_warn.keys():
                    continue
                city = this_warn["City"]
                company = this_warn["Company"]
                
                # PUT LOGIC TO WRITE COMPANY AND CITY TO DB


this_writer = Writer()
#print(this_writer.get_contacts_by_company("Walmart #3030", "WI"))
this_writer.update_companies()
