import uuid
from feedgen.feed import FeedGenerator
import json
import sqlite3
import logging
import time

class Writer:
           
    def store_contact(self, email, company, state, state_only):
        
        if state_only == "on":
            state_only = 1
        else:
            state_only = 0

        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            # set unit timestamp for created
            # set 0 for confirmed
            # set 0 for last notice
            # set field for only receiving warns from contact's state
            now = int(time.time())
            cur.execute('INSERT INTO contacts VALUES (?, ?, ?, ?, ?, ?, ?)', (email, company, state, state_only, 0, now, 0))
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

    def get_companies_like(self, this_string):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            query_string = 'SELECT company from companies where company like "%' + this_string + '%"'
            cur.execute(query_string)
            rows = cur.fetchall()
            new_rows = list()
            for row in rows:
                new_rows.append(row[0])
            return json.dumps(new_rows)
        except:
            logging.exception("Error getting contacts")


    def clear_table(self, table):

        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            cur.execute('DELETE FROM ' + table + ' WHERE 1=1')
            con.commit()
        except:
            logging.exception("Error clearing table: " + table)

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
#print(this_writer.get_companies_like('twit'))
#print(this_writer.get_contacts_by_company("Walmart #3030", "WI"))
# this_writer.update_companies()
#print(this_writer.get_all_companies())
#this_writer.get_all_states()
#this_writer.get_companies_by_state("CA")

