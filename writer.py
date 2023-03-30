from random import SystemRandom
import datetime
from rfeed import *

class Writer:                   
    # write rss data from list of WARN notice items
    def write_rss(self, notices_dict):

        for item in notices_dict.keys():
            # write guid for RSS object
            random = SystemRandom()
        
