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

reader = Reader()
#json.dumps(reader.xlsx_to_dict("ca_warn_data.xlsx"), default=str)
#print(json.dumps(reader.xlsx_to_dict("ca_warn_data.xlsx"), default=str))
print(reader.xlsx_to_dict(os.path.expanduser('~') + '/.warn-scraper/cache/ca/warn_report.xlsx'))
#print(reader.html_to_dict("./test_wa.html"))