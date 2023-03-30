import openpyxl
import json
from bs4 import BeautifulSoup
import os
class Reader:                   
    # convert excel file to csv
    def xlsx_to_dict(self, path):
        wb = openpyxl.load_workbook(path)
        worksheet = wb.active

        columns_names = list()
        sheet_dict = dict()
        for row in worksheet:
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

                    # ADD COUNTY/ADDRESS ETC!!!!!!!!!!!!
                    
                    
                    this_item = dict()
                    this_item['title'] = company
                    this_item['description'] = this_info
                    items_list.append(this_item)
                
                notice_dict['title'] = company
                notice_dict['description'] = 'See below list of notices'
                notice_dict['items'] = items_list
                return_dict[company] = notice_dict
        print(json.dumps(return_dict))
                


reader = Reader()
reader.format_data_from_xlsx(list())
#json.dumps(reader.xlsx_to_dict("ca_warn_data.xlsx"), default=str)
#print(json.dumps(reader.xlsx_to_dict("ca_warn_data.xlsx"), default=str))
#print(reader.xlsx_to_dict(os.path.expanduser('~') + '/.warn-scraper/cache/ca/warn_report.xlsx'))
#print(reader.html_to_dict("./test_wa.html"))