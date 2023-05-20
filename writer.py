import uuid
# import datetime
# import rfeed.rfeed as rf
from feedgen.feed import FeedGenerator
import json



class Writer:                   
    # write rss data from list of WARN notice items
    feed_list = list()
    def write_rss(self, notices_dict):

        for company in notices_dict.keys():
            # write guid for RSS object
            random =  uuid.uuid4()
            fg = FeedGenerator()
            fg.id(random)
            fg.title(company)
            fg.author( {'name':'John Doe','email':'john@example.kitchen'} )
            #fg.link( href='http://example.com', rel='alternate' )
            #fg.logo('http://ex.com/logo.jpg')
            #fg.subtitle('This is a cool feed!')
            fg.link( href='http://larskiesow.de/test.atom', rel='self' )
            fg.language('en')
            fg.description('See below items')
            fg.language('en')

            info = notices_dict[company]
            closing_or_layoff = info["Closing or Layoff"]
            initial_reporting_date = info["Initial Report Date"]
            print(company)
            if "Planned Starting Date" in info:
                planned_starting_date = info["Planned Starting Date"]
            city = info["City"]
            planned_no_affected_employees = info["Planned # Affected Employees"]
            random =  uuid.uuid4()
            fe = fg.add_entry()
            fe.title = company + " - " + closing_or_layoff + " - " + "Reported:" + initial_reporting_date + " - " + "Starting: " + planned_starting_date + " - " + "City:" + city + " - " + " Employees Affected: " + planned_no_affected_employees
            fe.link(href='http://lernfunk.de/feed')
            fe.enclosure('http://lernfunk.de/media/654321/1/file.mp3', 0, 'audio/mpeg')
            print(fe)
            # for this_item in notices_dict[company]:
            #     print(this_item)
            #     this_item = json.loads(this_item)
            #     closing_or_layoff = this_item["Closing or Layoff"]
            #     initial_reporting_date = this_item["Initial Report Date"]
            #     planned_starting_date = this_item["Planned Starting Date"]
            #     city = this_item["City"]
            #     planned_no_affected_employees = this_item["Planned # Affected Employees"]
            #     # write guid for RSS object
            #     random =  uuid.uuid4()
            #     fe = fg.add_entry()
            #     fe.title = this_item[company + " - " + closing_or_layoff + " - " + "Reported:" + initial_reporting_date + " - " + "Starting: " + planned_starting_date + " - " + "City:" + city]
            #     #fe.description = this_item['description']
            #     #fe.id(random)
            #     fe.link(href='http://lernfunk.de/feed')
            #     fe.enclosure('http://lernfunk.de/media/654321/1/file.mp3', 0, 'audio/mpeg')
            #     # feed = rf.Feed(notices_dict[company]['title'], )
            #     #items_list.append(itemified)
            
            #print(fg)
            #fg.rss_str(pretty=True)
            #fg.rss_file('/tmp/test.json')

            # list of rfeed Item objects from array in dict
            # items_list = list()
            # for this_item in notices_dict[company]['items']:
            #     #print(this_item)
            #     itemified = rf.Item(this_item['title'], 'www.google.com', this_item['description'], 'nonnimartin@gmail.com', 'warn notice', None, None, None, None)
            #     # feed = rf.Feed(notices_dict[company]['title'], )
            #     items_list.append(itemified)
            
            # print(rf.Feed(company, 'www.google.com', 'See notices below', 'en-US', None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, items_list).rss())

            
            
new_writer = Writer()
f = open("/tmp/test.json", "r")
json_content = f.read()
content_dict = json.loads(json_content)
new_writer.write_rss(content_dict)

        
