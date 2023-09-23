from feedgen.feed import FeedGenerator
import json
import sqlite3
import logging
import time
from uuid import uuid4
import hashlib


class Writer:
           
    def store_contact(self, email, company):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            # set unit timestamp for created
            # set 0 for confirmed
            # set 0 for last notice
            # set field for only receiving warns from contact's state
            now = int(time.time())
            # create user uuid
            user_uuid = uuid4()
            cur.execute('INSERT INTO contacts VALUES (?, ?, ?, ?, ?, ?, ?)', (user_uuid.hex, email, company, now, 0, 0, None))
            con.commit()
        except:
            logging.exception("Error writing to contacts")

    def make_api_token(self, user_id):
        
        f = open("./seed", "r")
        seed_load = json.loads(f.read())
        this_seed = seed_load["seed"]

        my_hash = hashlib.sha256(user_id.encode('utf-8') + this_seed.encode('utf-8'))
        return my_hash.hexdigest()

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

    def get_contacts_by_company(self, company):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            # comma makes the below a tuple, which is required
            cur.execute('SELECT * from contacts where (company like ?) and confirmed = 1', ("%" + company + "%",))
            rows = cur.fetchall()
            return rows
        except:
            logging.exception("Error getting contacts")

    def get_user_by_email(self, email):
        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            # comma makes the below a tuple, which is required
            cur.execute('SELECT * from contacts where (email = ?)', (email,))
            rows = cur.fetchall()
            return rows
        except:
            logging.exception("Error getting contacts")

    def validate_token(self, email, token):

        f = open("./seed", "r")
        seed_load    = json.loads(f.read())
        this_seed    = seed_load["seed"]
        this_writer  = Writer()
        this_user    = this_writer.get_user_by_email(email)
        stored_key   = this_user[0][-1]

        if stored_key == token:
            return True
        else:
            return False

    def unsubscribe(self, email):

        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            cur.execute('update contacts set confirmed = 0 where (email = ?)', (email,))
            con.commit()
            return True
        except:
            logging.exception("Error getting contacts")

    def resubscribe(self, email):

        try: 
            con = sqlite3.connect("warnDb.db")
            cur = con.cursor()
            cur.execute('update contacts set confirmed = 1 where (email = ?)', (email,))
            con.commit()
            return True
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


#print(this_writer.get_companies_like('twit'))
#print(this_writer.get_contacts_by_company("Walmart #3030", "WI"))
# this_writer.update_companies()
#print(this_writer.get_all_companies())
#this_writer.get_all_states()
#this_writer.get_companies_by_state("CA")
#this_writer = Writer()
# this_writer.unsubscribe("warnwarn@testwarn.com", "")
#this_writer.validate_token("warnwarn@testwarn.com", "")
#print(this_writer.validate_token("warnwarn@testwarn.com", "b87c39c003f010f5ea8fbd1d0abf219efa3c8b1fc39ff7ba4c7ab645ab22fd78"))
#this_writer.resubscribe("warnwarn@testwarn.com")

