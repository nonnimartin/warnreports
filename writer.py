import uuid
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

    def store_company_set(self, this_set):
        con = sqlite3.connect("warnDb.db")
        cur = con.cursor()
        for company_tuple in this_set:
            company = company_tuple[0]
            state = company_tuple[1]
            try: 
                cur.execute('INSERT OR REPLACE INTO companies VALUES (?, ?)', (company, state))
            except:
                logging.exception("Error writing to company")
        con.commit()

    def get_companies_by_state(self, state):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            # comma there to make param a tuple
            cur.execute('SELECT company from companies where (state = ?)', (state,))
            rows = cur.fetchall()
            prepped_rows = list()
            for row in rows:
                prepped_rows.append(row[0])
            sort_list = sorted(prepped_rows, key=lambda s: s.casefold())
            return json.dumps(sort_list)
        except:
            logging.exception("Error getting to companies by state")

    def get_all_states(self):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            cur.execute('SELECT DISTINCT state from companies')
            rows = cur.fetchall()
            return_list = list()
            for i in rows:
                return_list.append(i[0])
            sort_list = sorted(return_list, key=lambda s: s.casefold())
            return json.dumps(sort_list)
        except:
            logging.exception("Error getting to companies by state")

    def get_contacts_by_company(self, company, state):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            cur.execute('SELECT * from contacts where (company = ? and state = ?)', (company, state))
            rows = cur.fetchall()
            return rows
        except:
            logging.exception("Error getting contacts")

    def get_all_companies(self):

        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            cur.execute('SELECT * from companies')
            rows = cur.fetchall()
            return json.dumps(rows)
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


#this_writer = Writer()
#print(this_writer.get_contacts_by_company("Walmart #3030", "WI"))
# this_writer.update_companies()
#print(this_writer.get_all_companies())
#this_writer.get_all_states()
#this_writer.get_companies_by_state("CA")
