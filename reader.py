import json
import csv
import os
import logging
import writer
import boto3
#from pathlib import Path
import time
from dateutil.parser import *
import logging
import sys

class Reader:      

    def convert_by_state(self, state):

        conversion_dict_ak = {
            "Company" : "Company",
            "Notice Date" : "Initial Report Date",
            "Location" : "City",
            "Employees Affected" : "Planned # Affected Employees",
            "Layoff Date" : "No starting date specified",
            "Notes" : "Closing or Layoff"
        }

        conversion_dict_az = {
            "employer" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "Planned Starting Date" : "Planned Starting Date",
            "warn_type" : "Closing or Layoff"
        }

        conversion_dict_al = {
            "Company" : "Company",
            "Initial Report Date" : "Initial Report Date",
            "City" : "City",
            "Planned # Affected Employees" : "Planned # Affected Employees",
            "Closing or Layoff" : "Closing or Layoff",
            "Planned Starting Date" : "Planned Starting Date"
        }

        conversion_dict_ca = {
            "company" : "Company",
            "notice_date" : "Initial Report Date",
            "address" : "City",
            "num_employees" : "Planned # Affected Employees",
            "layoff_or_closure" : "Closing or Layoff",
            "effective_date" : "Planned Starting Date"
        }

        conversion_dict_co = {
            "company" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "jobs" : "Planned # Affected Employees",
            "occupations" : "Closing or Layoff",
            "begin_date" : "Planned Starting Date"
        }

        conversion_dict_ct = {
            "company" : "Company",
            "warn_date" : "Initial Report Date",
            "layoff_location" : "City",
            "number_workers" : "Planned # Affected Employees",
            "closing" : "Closing or Layoff",
            "layoff_date" : "Planned Starting Date"
        }

        conversion_dict_dc = {
            "Organization Name" : "Company",
            "Notice Date" : "Initial Report Date",
            "city" : "City",
            "Number toEmployees Affected" : "Planned # Affected Employees",
            "layoff_or_closure" : "Closing or Layoff",
            "Effective Layoff Date" : "Planned Starting Date"
        }

        conversion_dict_de = {
            "employer" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "warn_type" : "Closing or Layoff",
            
        }

        conversion_dict_fl = {
            "Company Name" : "Company",
            "State Notification Date" : "Initial Report Date",
            "City" : "City",
            "Employees Affected" : "Planned # Affected Employees",
            "Notice Type" : "Closing or Layoff",
            "Layoff Date" : "Planned Starting Date"
        }

        conversion_dict_ia = {
            "Company" : "Company",
            "Notice Date" : "Initial Report Date",
            "City" : "City",
            "Emp #" : "Planned # Affected Employees",
            "Notice Type" : "Closing or Layoff",
            "Layoff Date" : "Planned Starting Date"
        }

        conversion_dict_in = {
            "Company" : "Company",
            "Notice Date" : "Initial Report Date",
            "City" : "City",
            "Affected Workers" : "Planned # Affected Employees",
            "Notice Type" : "Closing or Layoff",
            "LO/CL Date" : "Planned Starting Date"
        }

        conversion_dict_ks = {
            "employer" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "warn_type" : "Closing or Layoff",
            "LO/CL Date" : "Planned Starting Date"
        }

        conversion_dict_md = {
            "Company" : "Company",
            "Notice Date" : "Initial Report Date",
            "Location" : "City",
            "Total Employees" : "Planned # Affected Employees",
            "Type" : "Closing or Layoff",
            "Effective Date" : "Planned Starting Date"
        }

        conversion_dict_me = {
            "employer" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "warn_type" : "Closing or Layoff",
            "notice_date" : "Planned Starting Date"
        }

        conversion_dict_mo = {
            "Title" : "Company",
            "Received Sort descending" : "Initial Report Date",
            "Location(s)" : "City",
            "# affected" : "Planned # Affected Employees",
            "Type" : "Closing or Layoff",
            "Layoff date(s)" : "Planned Starting Date"
        }

        conversion_dict_ny = {
            "company_name" : "Company",
            "notice_dated" : "Initial Report Date",
            "date_posted" : "City",
            "Number Affected" : "Planned # Affected Employees",
            "Dislocation Type" : "Closing or Layoff"
        }

        conversion_dict_ok = {
            "employer" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "warn_type" : "Closing or Layoff"
        }

        conversion_dict_or = {
            "Company Name" : "Company",
            "Received Date" : "Initial Report Date",
            "Location" : "City",
            "Laid Off" : "Planned # Affected Employees",
            "Layoff Type" : "Closing or Layoff",
            "Layoff Date" : "Planned Starting Date"
        }

        conversion_dict_sc = {
            "company" : "Company",
            "date" : "Initial Report Date",
            "location" : "City",
            "jobs" : "Planned # Affected Employees",
            "Layoff Type" : "Closing or Layoff",
            "date" : "Planned Starting Date"
        }

        conversion_dict_tx = {
            "JOB_SITE_NAME" : "Company",
            "NOTICE_DATE" : "Initial Report Date",
            "CITY_NAME" : "City",
            "TOTAL_LAYOFF_NUMBER" : "Planned # Affected Employees",
            "Layoff Type" : "Closing or Layoff",
            "LayOff_Date" : "Planned Starting Date"
        }

        conversion_dict_ut = {
            "Company Name" : "Company",
            "Date of Notice" : "Initial Report Date",
            "Location" : "City",
            "Affected Workers" : "Planned # Affected Employees",
            "Layoff Type" : "Closing or Layoff",
            "Layoff Date" : "Planned Starting Date"
        }

        conversion_dict_va = {
            "Company Name" : "Company",
            "Notice Date" : "Initial Report Date",
            "Location City" : "City",
            "Employees Affected" : "Planned # Affected Employees",
            "Layoff" : "Closing or Layoff",
            "Impact Date" : "Planned Starting Date"
        }

        conversion_dict_vt = {
            "employer" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "warn_type" : "Closing or Layoff",
            "Impact Date" : "Planned Starting Date"
        }

        conversion_dict_wi = {
            "Company" : "Company",
            "Notice Received" : "Initial Report Date",
            "City" : "City",
            "Affected Workers" : "Planned # Affected Employees",
            "Original Notice Type / Update Type" : "Closing or Layoff",
            "Layoff Begin Date" : "Planned Starting Date"
        }

        if state == "ak":
            return conversion_dict_ak
        elif state == "az":
            return conversion_dict_az
        elif state == "al":
            return conversion_dict_al
        elif state == "ca":
            return conversion_dict_ca
        elif state == "co":
            return conversion_dict_co
        elif state == "ct":
            return conversion_dict_ct
        elif state == "dc":
            return conversion_dict_dc
        elif state == "de":
            return conversion_dict_de
        elif state == "fl":
            return conversion_dict_fl
        elif state == "ia":
            return conversion_dict_ia
        elif state == "in":
            return conversion_dict_in
        elif state == "ks":
            return conversion_dict_ks
        elif state == "md":
            return conversion_dict_md
        elif state == "me":
            return conversion_dict_me
        elif state == "mo":
            return conversion_dict_mo
        elif state == "ny":
            return conversion_dict_ny
        elif state == "ok":
            return conversion_dict_ok
        elif state == "or":
            return conversion_dict_or
        elif state == "sc":
            return conversion_dict_sc
        elif state == "tx":
            return conversion_dict_tx
        elif state == "ut":
            return conversion_dict_ut
        elif state == "va":
            return conversion_dict_va
        elif state == "vt":
            return conversion_dict_vt
        elif state == "wi":
            return conversion_dict_wi
        else:
            return
        
    def has_numbers(input):
        # check if date value contains numbers to eliminate garbage rows
        return any(char.isdigit() for char in input)
    
    def has_letters(input):
        # adding common nonalpha chars
        chars = "!#%&?"
        if any(ext in input for ext in chars):
            return True
        if any(c.isalpha() for c in input):
            return True

    def get_date(input):
        # various attempts at handling irregular dates
        if not Reader.has_numbers(input):
            return False
        try: 
            return str(parse(str(input), fuzzy=True).date())

        except ValueError:
            return False
    
    # convert csv to dict
    def csv_to_dict(self, path, state):
        # this will have to be diff for each CSV, as they have diff structure
        first_loop = True
        headers_list = list()
        return_dict = dict()
        convert_dict = self.convert_by_state(state)
        with open(path,'r') as data:
            for line in csv.reader(data):

                if first_loop == True:
                    headers_list = line
                    first_loop = False
                    continue
                
                company = str()
                if first_loop == False:
                    this_dict = dict()
                    
                    # variable to exclude line from return dictionary
                    this_header = str()
                    for item in line:
                        header_index = line.index(item)

                        if (header_index > len(headers_list)-1):
                            continue
                        if headers_list[header_index] in convert_dict:
                            this_header = convert_dict[headers_list[header_index]]
                            if this_header == "Company":
                                company = item.split('\n')[0].strip()
                                this_dict["Company"] = company
                                continue
                            this_dict[this_header] = item
                            continue 
                    
                    if "Initial Report Date" not in this_dict:
                        continue
                    if not Reader.get_date(this_dict["Initial Report Date"]):
                        continue
                    
                    if Reader.get_date(this_dict["Initial Report Date"]):
                        parsed_date = parse(Reader.get_date(this_dict["Initial Report Date"]))
                        rep_epoch = int(parsed_date.timestamp())
                        # if the warn is over year old, keep going
                        if ((int(time.time()) - rep_epoch) > 31536000):
                            continue
                check_dict = ["City", "Initial Report Date", "Planned # Affected Employees", "Closing or Layoff", "Planned Starting Date"]
                for field in check_dict:
                    if field not in this_dict:
                        this_dict[field] = "N/A or Not Provided"
                return_dict[company] = this_dict

        return json.dumps(return_dict)
    
    def write_to_disk(self, json, state):
        try:
            filehandle = open(os.path.expanduser('~') + '/git/warn_reporter/' + 'reports_json/' + state + '.json', 'w')
            filehandle.write(json)
            filehandle.close()
        except:
             logging.exception('Error writing file to disk: ' + state)

    def get_config():
        # return config file content as dictionary
        with open(os.path.expanduser('~') + '/git/warn_reporter/' + 'config.json', 'r') as file:
            return json.loads(file.read())

    def send_out_reports(self):
        # go through all reports and map reports to contacts
        states_list = ["AL", "AZ", "CA", "CO", "DC", "DE", "IA", "IN", "KS", "MD", "ME", "MO", "NY", "OK", "OR", "SC", "TX", "UT", "VA", "VT", "WI"]
        this_writer = writer.Writer()

        for state in states_list:
            # open each state's file 
            parsed_dict = dict()
            with open(os.path.expanduser('~') + '/git/warn_reporter/' + 'reports_json/' + state.lower() + '.json', "r") as file:
                parsed_dict = json.loads(json.load(file))

            # list each line in 
            for line in parsed_dict.keys():
                
                if isinstance(line, str):
                    line_dict = parsed_dict[line]
                    report_date_str = line_dict['Initial Report Date']
                    # parse most date formats to datetime
                    report_dt = Reader.get_date(report_date_str)
                    report_epoch = int(parse(report_dt).timestamp())
                    # if the warn is over 2 months old, keep going
                    if ((int(time.time()) - report_epoch) > 5260000):
                        continue
                    
                    if 'Company' not in line_dict.keys():
                        continue
                    else:
                        this_company = line_dict['Company']
                        folks_to_contact = this_writer.get_contacts_by_company(this_company)
                        if len(folks_to_contact) > 0:
                            this_warning = Reader().get_warnings_by_state(line_dict['Company'], state)
                            
                            if this_warning == False:
                                continue
                            for person in folks_to_contact:
                                #see if notified in last 5 days
                                # by subtracting 431965 from unix epoch
                                if not ((int(time.time()) - 431965) < person[4]):
                                    this_config = Reader.get_config()
                                    # construct email content
                                    this_body = '<b> WARN Report for ' + this_warning['Company'] + ' in ' + this_warning['City'] + '</b>' + '<br>' + 'Planned # Affected Employees: ' + this_warning['Planned # Affected Employees'] + '<br>' + 'Initial Report Date: ' + this_warning['Initial Report Date'] + '<br>' + 'Closing or Layoff: ' + this_warning['Closing or Layoff'] + '<br>' + 'Planned Starting Date: ' + this_warning['Planned Starting Date']
                                    # send email
                                    this_subject = this_warning['Planned # Affected Employees'] + ' to be laid off at ' + this_warning['City'] + ' ' + this_warning['Company']
                                    this_body = '<br>' + this_body + '<br>' + '<br>' + '<a href="' + this_config['hostname'] + '/unsubscribe?email=' + person[1] + '&token=' + person[6] + '">Click here to unsubscribe from these emails.</a>'
                                    Reader().send_email(this_config['email_account'], person[1], this_subject, this_body)
                                    # make this conditional upon success
                                    # update lastNotice in db
                                    this_writer.update_last_notice(person[0])
                            continue
        return True
    
    def update_companies(self):
        this_writer = writer.Writer()
        # go through all reports and map reports to contacts
        states_list = ["AL", "AK", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "IA", "IN", "KS", "MD", "ME", "MO", "NY", "OK", "OR", "SC", "TX", "UT", "VA", "VT", "WI"]
        company_set = set()
        for state in states_list:
            this_path = os.path.expanduser('~') + '/git/warn_reporter/' + 'reports_json/' + state.lower() + '.json'
            if not os.path.isfile(this_path):
                try:
                    with open(this_path, "w+") as to_open:
                        pass
                except:
                    logging.exception('Error writing file to disk: ' + this_path)
            
            parsed_dict = dict()
            with open(this_path, 'r') as this_file:
                data = this_file.read()
                parsed_dict = json.loads(json.loads(data))

            for line in parsed_dict.keys():
                if isinstance(line, str):
                    line_dict = parsed_dict[line]
                    if 'Company' not in line_dict.keys() or len(line_dict['Company']) == 0:
                        continue
                    else:
                        company = line_dict['Company']
                        company_set.add((company, state))
        # write companies set to db
        this_writer.store_company_set(company_set)
        return
    
    def get_warnings_by_state(self, company, state):
        this_path = os.path.expanduser('~') + '/git/warn_reporter/' + 'reports_json/' + state.lower() + '.json'
        if os.path.exists(this_path):
            f = open(this_path)
            report_dict = json.loads(json.loads(f.read()))
            if company in report_dict.keys():
                return report_dict[company]
            else:
                return False
            
    def send_email(self, sender, recipient, subject, body):
        
        ses_client = boto3.client('ses', region_name='us-west-2')  # Replace with your preferred region
        # Create the email message
        message = {
            'Subject': {'Data': subject},
            'Body': {
                    'Text': {'Data': body,'Charset': 'UTF-8'},
                    'Html': {'Data': body, 'Charset': 'UTF-8'}
                     }
        }
        
        # Send the email
        response = ses_client.send_email(
            Source=sender,
            Destination={'ToAddresses': [recipient]},
            Message=message
        )
        # Check the response
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            print('Email sent successfully!')
        else:
            print('Failed to send email.')
