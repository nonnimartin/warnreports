import os
import csv
import json

date_headers_list = [
   "notice_dated",
   "Impact Date",
   "Layoff Begin Date",
   "Effective Layoff Date",
   "begin_date",
   "end_date",
   "State Notification Date",
   "Notice Received",
   "date",
   "Initial Report Date",
   "date_posted",
   "notice_date",
   "LayOff_Date",
   "Planned Starting Date",
   "closing_date",
   "Received Date",
   "Layoff date(s)",
   "effective_date",
   "Closing Date",
   "WFDD_RECEIVED_DATE",
   "LO/CL Date",
   "Closure",
   "Notice Date",
   "NOTICE_DATE",
   "warn_date",
   "dropdown",
   "Received Sort descending",
   "received_date",
   "Effective Date",
   "Layoff Date",
   "Date of Notice",
   "layoff_date"
]

date_headers_dict = {
    "az": [
        "notice_date"
    ],
    "al": [
        "Initial Report Date",
        "Planned Starting Date"
    ],
    "mo": [
        "Received Sort descending",
        "Layoff date(s)"
    ],
    "or": [
        "Layoff Date",
        "Received Date"
    ],
    "tx": [
        "NOTICE_DATE",
        "LayOff_Date",
        "WFDD_RECEIVED_DATE"
    ],
    "ak": [
        "Notice Date",
        "Layoff Date"
    ],
    "ct": [
        "warn_date",
        "layoff_date",
        "closing_date"
    ],
    "vt": [
        "notice_date"
    ],
    "va": [
        "Notice Date",
        "Impact Date",
        "Closure"
    ],
    "ca": [
        "notice_date",
        "effective_date",
        "received_date"
    ],
    "dc": [
        "Notice Date",
        "Effective Layoff Date"
    ],
    "fl": [
        "State Notification Date",
        "Layoff Date"
    ],
    "de": [
        "notice_date"
    ],
    "ia": [
        "Notice Date",
        "Layoff Date"
    ],
    "ks": [
        "notice_date"
    ],
    "sc": [
        "date"
    ],
    "in": [
        "Notice Date",
        "LO/CL Date"
    ],
    "wi": [
        "Notice Received",
        "Layoff Begin Date"
    ],
    "md": [
        "Notice Date",
        "Effective Date"
    ],
    "co": [
        "received_date",
        "end_date",
        "notice_date",
        "begin_date",
        "dropdown"
    ],
    "ut": [
        "Date of Notice"
    ],
    "me": [
        "notice_date"
    ],
    "ny": [
        "date_posted",
        "notice_dated",
        "Notice Date",
        "Layoff Date",
        "Closing Date"
    ],
    "ok": [
        "notice_date"
    ]
    }

path = "/Users/jon/.warn-scraper/exports"
main_dict = dict()
main_list = list()
unique = set()

def get_headers():
    for filename in os.listdir(path):
        first_loop = True
        f = os.path.join(path, filename)
        # checking if it is a file
        if os.path.isfile(f):
            with open(f,'r') as data:
                for line in csv.reader(data):
                    if first_loop == True:
                        headers_list = line
                        first_loop = False
                        for header in headers_list:
                            unique.add(header)
                            main_list = [elem for elem in unique]
                            print(main_list)

def match_headers_to_comp():
    for filename in os.listdir(path):
        first_loop = True
        f = os.path.join(path, filename)
        # checking if it is a file
        if os.path.isfile(f):
            with open(f,'r') as data:
                for line in csv.reader(data):
                    if first_loop == True:
                        this_header_list = list()
                        headers_list = line
                        first_loop = False
                        for header in headers_list:
                            if header in date_headers_list:
                                this_header_list.append(header)
                        main_dict[f.split(".csv")[0]] = this_header_list
    
    return json.dumps(main_dict)

#print(match_headers_to_comp())
#print(type(date_headers_json))
#print(json.dumps(main_dict))