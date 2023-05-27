import json
import csv
import os
import logging

class Reader:                   

    def convert_by_state(self, state):

        conversion_dict_az = {
            "employer" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "Planned Starting Date" : "No starting date specified",
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
            "city" : "City",
            "num_employees" : "Planned # Affected Employees",
            "layoff_or_closure" : "Closing or Layoff",
            "effective_date" : "Planned Starting Date"
        }

        conversion_dict_co = {
            "company" : "Company",
            "received_date" : "Initial Report Date",
            "city" : "City",
            "jobs" : "Planned # Affected Employees",
            "occupations" : "Closing or Layoff",
            "begin_date" : "Planned Starting Date"
        }

        conversion_dict_dc = {
            "Organization Name" : "Company",
            "Notice Date" : "Initial Report Date",
            "city" : "City",
            "Number toEmployees Affected" : "Planned # Affected Employees",
            "layoff_or_closure" : "Closing or Layoff",
            "begin_date" : "Planned Starting Date"
        }

        conversion_dict_de = {
            "employer" : "Company",
            "Notice Date" : "Initial Report Date",
            "City" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "warn_type" : "Closing or Layoff"
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
            "Effective Date" : "Planned Starting Date"
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
            "date_posted" : "Initial Report Date",
            "City" : "City",
            "Number Affected" : "Planned # Affected Employees",
            "Dislocation Type" : "Closing or Layoff",
            "notice_dated" : "Planned Starting Date"
        }

        conversion_dict_ok = {
            "employer" : "Company",
            "date_posted" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "warn_type" : "Closing or Layoff",
            "notice_date" : "Planned Starting Date"
        }

        conversion_dict_or = {
            "company" : "Company",
            "date" : "Initial Report Date",
            "location" : "City",
            "jobs" : "Planned # Affected Employees",
            "Layoff Type" : "Closing or Layoff",
            "Layoff Date" : "Planned Starting Date"
        }

        conversion_dict_sc = {
            "Company Name" : "Company",
            "Received Date" : "Initial Report Date",
            "Location" : "City",
            "Laid Off" : "Planned # Affected Employees",
            "Layoff Type" : "Closing or Layoff",
            "Layoff Date" : "Planned Starting Date"
        }

        conversion_dict_tx = {
            "JOB_SITE_NAME" : "Company",
            "NOTICE_DATE" : "Initial Report Date",
            "CITY_NAME" : "City",
            "TOTAL_LAYOFF_NUMBER" : "Planned # Affected Employees",
            "Layoff Type" : "Closing or Layoff",
            "Layoff Date" : "Planned Starting Date"
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
            "Layoff Type" : "Closing or Layoff",
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

        if state == "az":
            return conversion_dict_az
        elif state == "al":
            return conversion_dict_al
        elif state == "ca":
            return conversion_dict_ca
        elif state == "co":
            return conversion_dict_co
        elif state == "dc":
            return conversion_dict_dc
        elif state == "de":
            return conversion_dict_de
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
        else:
            return
    

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
                    this_header = str()
                    for item in line:
                        header_index = line.index(item)

                        if (header_index > len(headers_list)-1):
                            continue
                        if headers_list[header_index] in convert_dict:
                            this_header = convert_dict[headers_list[header_index]]
                            this_dict[this_header] = item
                        if this_header == "Company":
                            company = item
                    # we will have to put n/a into any fields not included
                    check_dict = ["City", "Initial Report Date", "Planned # Affected Employees", "Closing or Layoff", "Planned Starting Date"]
                    for field in check_dict:
                        if field not in this_dict:
                            this_dict[field] = "N/A or Not Provided"
                    return_dict[company] = this_dict
        return json.dumps(return_dict)
    
    def write_to_disk(self, json, state):
        try:
            filehandle = open('./reports_json/' + state + '.json', 'w')
            filehandle.write(json)
            filehandle.close()
        except:
             logging.exception('Error writing file to disk: ' + state)

# print(json.dumps(reader.csv_to_dict(os.path.expanduser('~') + '/.warn-scraper/exports/mo.csv', 'mo')))
#json.dumps(reader.csv_to_dict(os.path.expanduser('~') + '/.warn-scraper/exports/az.csv', 'az'))
