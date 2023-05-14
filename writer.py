import uuid
# import datetime
# import rfeed.rfeed as rf
from feedgen.feed import FeedGenerator


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
            print(company)

            for this_item in notices_dict[company]['items']:
                # write guid for RSS object
                random =  uuid.uuid4()
                fe = fg.add_entry()
                fe.title = this_item['title']
                fe.description = this_item['description']
                fe.id(random)
                fe.link(href='http://lernfunk.de/feed')
                fe.enclosure('http://lernfunk.de/media/654321/1/file.mp3', 0, 'audio/mpeg')
                # feed = rf.Feed(notices_dict[company]['title'], )
                #items_list.append(itemified)
            
            print(fg)
            #fg.rss_str(pretty=True)
            fg.rss_file('./test.xml')

            # list of rfeed Item objects from array in dict
            # items_list = list()
            # for this_item in notices_dict[company]['items']:
            #     #print(this_item)
            #     itemified = rf.Item(this_item['title'], 'www.google.com', this_item['description'], 'nonnimartin@gmail.com', 'warn notice', None, None, None, None)
            #     # feed = rf.Feed(notices_dict[company]['title'], )
            #     items_list.append(itemified)
            
            # print(rf.Feed(company, 'www.google.com', 'See notices below', 'en-US', None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, items_list).rss())

            
            

        
