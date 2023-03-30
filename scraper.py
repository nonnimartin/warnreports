from warn.scrapers import al, az, ca, co, dc, de, ia, ks, md, me, mo, ny, ok, sc, tx, ut, va, vt, wi

class Scraper: 
    def scrape_all():

        # commenting out to avoid error with "ABM Aviation, Inc."
        al.scrape()
        # az.scrape()
        ca.scrape()
        # co.scrape()
        # dc.scrape()
        # de.scrape()
        # ia.scrape()
        # ks.scrape()
        # md.scrape()
        # me.scrape()
        # mo.scrape()
        # ny.scrape()
        # ok.scrape()
        # sc.scrape()
        # tx.scrape()
        # ut.scrape()
        # va.scrape()
        # vt.scrape()
        # wi.scrape()

new_scraper = Scraper
new_scraper.scrape_all()
