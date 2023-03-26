import pandas as pd
import csv
import openpyxl

class Reader:                   
    # convert excel file to csv
    def xlsx_to_dict(self, path):
        wb = openpyxl.load_workbook(path)
        worksheet = wb.active
        csv_dict = dict()

        columns_names = list()
        counter = 0
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
                sheet_dict[counter] = this_dict
                counter += 1

        return sheet_dict
    
reader = Reader()
print(reader.xlsx_to_dict("ca_warn_data.xlsx"))