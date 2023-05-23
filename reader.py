import openpyxl
import json
import csv
#from bs4 import BeautifulSoup
import os

class Reader:                   
    # convert excel file to csv
    def xlsx_to_dict(self, path):
        wb = openpyxl.load_workbook(path)
        worksheet = wb.active

        columns_names = list()
        sheet_dict = dict()
        for row in worksheet:
            row_len = row.split(",")
            if len(columns_names) == 0:
                # if first loop, just populate list of column headers
                for cell in row:
                    columns_names.append(cell.value)
            else:
                # populate
                this_dict = dict()
                for header in columns_names:
                    this_index = columns_names.index(header)
                    this_dict[header] = row[this_index].value
                if this_dict["Company"] not in sheet_dict.keys():
                    company_name = this_dict["Company"]
                    new_list = list()
                    new_list.append(this_dict)
                    sheet_dict[company_name] = new_list
                elif this_dict["Company"] in sheet_dict.keys():
                    company_name = this_dict["Company"]
                    current_list = sheet_dict[company_name]
                    current_list.append(this_dict)
                    sheet_dict[company_name] = current_list

        return sheet_dict

    def convert_by_state(self, state):

        conversion_dict_az = {
            "employer" : "Company",
            "notice_date" : "Initial Report Date",
            "city" : "City",
            "number_of_employees_affected" : "Planned # Affected Employees",
            "Planned Starting Date" : "No starting date specified"
        }

        conversion_dict_al = {
            "Company" : "Company",
            "Initial Report Date" : "Initial Report Date",
            "City" : "City",
            "Planned # Affected Employees" : "Planned # Affected Employees",
            "Closing or Layoff" : "Closing or Layoff",
            "Planned Starting Date" : "Planned Starting Date"
        }

        if state == "az":
            return conversion_dict_az
        elif state == "al":
            return conversion_dict_al
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
                    for item in line:
                        header_index = line.index(item)
                        print(convert_dict)
                        if headers_list[header_index] in convert_dict:
                            this_header = convert_dict[headers_list[header_index]]
                            this_dict[this_header] = item
                        if this_header == "Company":
                            company = item
                    # we will have to put n/a into any fields not included
                    return_dict[company] = this_dict
        return return_dict
                    
                        
            

    # convert html to dict
    def html_to_dict(self, path):
        with open(path) as fp:
            soup = BeautifulSoup(fp, 'html.parser')
            print(soup.find_all('table'))
            # return soup

    def format_data_from_xlsx(self, paths_list):
        this_reader = Reader()
        return_dict = dict()
        # for list of paths, format data into fields ready for rss
        
        xlsx_dict = this_reader.xlsx_to_dict(os.path.expanduser('~') + '/.warn-scraper/cache/ca/warn_report.xlsx')
        
        # test with one case
        for company in xlsx_dict:
            # ignore numbered headers and loop through companies
            if not str(company).isnumeric():
                # list of notices for "items" bit of rss doc
                items_list = list()
                notice_dict = dict()
                # loop through company's notices
                for notice in xlsx_dict[company]:
                    this_company = notice['Company']
                    layoff_or_closure = notice['Layoff/\nClosure']
                    number_employees = notice['No. Of\nEmployees']
                    effective_date = str(notice['Notice\nDate'])
                    date_received = str(notice['Received\nDate'])
                    this_info = this_company + ' - ' + layoff_or_closure + ' - ' + 'No. of Employees: ' + str(number_employees) + ' - Effective Date: ' + effective_date + ' - Date Received: ' + date_received
                    notice_dict['title'] = this_company
                    
                    this_item = dict()
                    this_item['title'] = company
                    this_item['description'] = this_info
                    items_list.append(this_item)
                
                notice_dict['title'] = company
                notice_dict['description'] = 'See below list of notices'
                notice_dict['items'] = items_list
                return_dict[company] = notice_dict

        return return_dict
                


reader = Reader()

print(json.dumps(reader.csv_to_dict(os.path.expanduser('~') + '/.warn-scraper/exports/az.csv', 'az')))
#json.dumps(reader.csv_to_dict(os.path.expanduser('~') + '/.warn-scraper/exports/az.csv', 'az'))
