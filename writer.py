import json
import sqlite3
import logging
import time
from uuid import uuid4
import hashlib
import logging
import os
import settings


class Writer:
           
    def make_contact(self, email, company):
        try: 
            con = get_conn()
            cur = con.cursor()
            # set unit timestamp for created
            # set 0 for confirmed
            # set 0 for last notice
            # set field for only receiving warns from contact's state
            # create api token
            now = int(time.time())
            # create user uuid
            user_uuid = uuid4().hex
            token = Writer.make_api_token(user_uuid)
            cur.execute('INSERT INTO contacts VALUES (?, ?, ?, ?, ?, ?, ?)', (user_uuid, email, company, now, 0, 0, token))
            con.commit()
        except:
            logging.exception("Error writing to contacts")

    def update_last_notice(self, user_id):
        try: 
            con = get_conn()
            cur = con.cursor()
            now = int(time.time())
            cur.execute('UPDATE contacts SET lastNotice = (?) where id = (?)', (now, user_id))
            con.commit()
        except:
            logging.exception("Error writing to contacts")

    def is_duplicate_user(self, email, company):
        try: 
            con = get_conn()
            cur = con.cursor()
            cur.execute('SELECT * from contacts where email = (?) and company = (?)', (email, company))
            if len(cur.fetchall()) > 0:
                return True
            else:
                return False
        except:
            logging.exception("Error writing to contacts")

    def make_api_token(user_id):
        my_hash = hashlib.sha256(user_id.encode('utf-8') + settings.SEED.encode('utf-8'))
        return my_hash.hexdigest()

    def store_company(self, company, state):
        try: 
            con = get_conn()
            cur = con.cursor()
            cur.execute('INSERT INTO companies VALUES (?, ?)', (company, state))
            con.commit()
        except:
            logging.exception("Error writing to company")

    def store_company_set(self, this_set):
        con = get_conn()
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
            con = get_conn()
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
            con = get_conn()
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
            con = get_conn()
            cur = con.cursor()
            # comma makes the below a tuple, which is required
            cur.execute('SELECT * from contacts where (company like ?) and confirmed = 1', ("%" + company + "%",))
            rows = cur.fetchall()
            return rows
        except:
            logging.exception("Error getting contacts")

    def get_user_by_email(self, email):
        try: 
            con = get_conn()
            cur = con.cursor()
            # comma makes the below a tuple, which is required
            cur.execute('SELECT * from contacts where (email = ?)', (email,))
            rows = cur.fetchall()
            return rows
        except:
            logging.exception("Error getting contacts")

    def validate_token(self, email, token):
        
        this_writer   = Writer()
        users_list    = this_writer.get_user_by_email(email)

        if len(users_list) == 0:
            return False

        for user in users_list:
            stored_key   = user[-1]

            if stored_key == token:
                return True
        
        return False


    def unsubscribe(self, email):

        try: 
            con = get_conn()
            cur = con.cursor()
            cur.execute('update contacts set confirmed = 0 where (email = ?)', (email,))
            con.commit()
            return True
        except:
            logging.exception("Error getting contacts")

    def confirm(self, email):

        try: 
            con = get_conn()
            cur = con.cursor()
            cur.execute('update contacts set confirmed = 1 where (email = ?)', (email,))
            con.commit()
            return True
        except:
            logging.exception("Error getting contacts")

    def get_all_companies(self):

        try: 
            con = get_conn()
            cur = con.cursor()
            cur.execute('SELECT * from companies')
            rows = cur.fetchall()
            return json.dumps(rows)
        except:
            logging.exception("Error getting contacts")

    def get_companies_like(self, this_string):
        try: 
            con = get_conn()
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

    def get_token_for_user(self, email):
        try: 
            con = get_conn()
            cur = con.cursor()
            cur.execute('SELECT api_token from contacts where (email = ?)', (email,))
            rows = cur.fetchall()

            # since users can have more than one entry, give first of api tokens
            return rows[0][-1]
        except:
            logging.exception("Error getting contacts")


    def clear_table(self, table):

        try: 
            con = get_conn()
            cur = con.cursor()
            cur.execute('DELETE FROM ' + table + ' WHERE 1=1')
            con.commit()
        except:
            logging.exception("Error clearing table: " + table)
        

    def update_companies(self):
        states_list = ["AL", "AZ", "CA", "CO", "DC", "DE", "IA", "IN", "KS", "MD", "ME", "MO", "NY", "OK", "OR", "SC", "TX", "UT", "VA", "VT", "WI"]
        
        for state in states_list:
            f = open(settings.REPORTS_DIR + '/' + state.lower() + ".json")
            parsed_dict = json.load(f)
            for this_company in parsed_dict.keys():
                this_warn = parsed_dict[this_company]
                if "Company" not in this_warn.keys():
                    continue
                city = this_warn["City"]
                company = this_warn["Company"]
                
                # PUT LOGIC TO WRITE COMPANY AND CITY TO DB


def get_conn():
    return sqlite3.connect(settings.DB_FILE)
