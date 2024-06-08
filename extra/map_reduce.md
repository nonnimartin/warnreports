# Map Reduce Illustration

## Report

### Base

```sql
SELECT
    report.id,
    report.company,
    report.company_norm,
    report.reported,
    report.state,
    report.created,
    report.location,
    report.starting,
    report.employees,
    report.action,
    report.url
FROM report
WHERE report.id IN (
  '0000dad2-a7ad-5887-b87d-13fedcd6f854'::UUID,
  '005c88b7-49f7-57c9-8099-53370fb91579'::UUID,
  '1d6cc39d-0bb3-5ee3-ab40-96a066c00d46'::UUID,
  '36a96ce6-811f-5716-ab5c-c63da238e16e'::UUID
)
ORDER BY report.id
```

```json
[
  {
    "id": "0000dad2-a7ad-5887-b87d-13fedcd6f854",
    "company": "Scale AI, Inc.",
    "company_id": "2c3ea871-ae2e-590f-ae9f-e0dfaea3531e",
    "state": "CA",
    "location": null,
    "reported": "2023-01-09T00:00:00-08:00",
    "starting": "2023-03-31T00:00:00-07:00",
    "employees": 2,
    "action": "Layoff Permanent",
    "url": "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn-report-for-7-1-2022-to-06-30-2023.pdf"
  },
  {
    "id": "005c88b7-49f7-57c9-8099-53370fb91579",
    "company": "DIAMOND EXTERIORS INC",
    "company_id": "6daa3c95-36ee-5166-96e9-6b0a8a71c534",
    "state": "IL",
    "location": "WOODSTOCK",
    "reported": "2000-02-25T00:00:00-06:00",
    "starting": null,
    "employees": 78,
    "action": "Plant Closure",
    "url": "https://dceo.illinois.gov/workforcedevelopment/warn.html"
  },
  {
    "id": "1d6cc39d-0bb3-5ee3-ab40-96a066c00d46",
    "company": "Walmart",
    "company_id": "d6a0f94f-47d7-5cbb-a788-05df3bb543e0",
    "state": "CA",
    "location": "850 Cherry Avenue  San Bruno CA 94066",
    "reported": "2024-05-17T00:00:00-07:00",
    "starting": "2024-08-09T00:00:00-07:00",
    "employees": 388,
    "action": "Layoff Permanent",
    "url": "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx"
  },
  {
    "id": "36a96ce6-811f-5716-ab5c-c63da238e16e",
    "company": "Walmart Inc.",
    "company_id": "d6a0f94f-47d7-5cbb-a788-05df3bb543e0",
    "state": "IL",
    "location": "Chicago",
    "reported": "2023-04-28T00:00:00-05:00",
    "starting": null,
    "employees": 439,
    "action": "Layoff",
    "url": "https://dceo.illinois.gov/workforcedevelopment/warn.html"
  }
]
```

### Join naics

```sql
SELECT
    report.id,
    report.company,
    report.company_norm,
    report.reported,
    report.state,
    report.created,
    report.location,
    report.starting,
    report.employees,
    report.action,
    report.url,
    naics.id AS naics_id,
    naics.code,
    naics.title
FROM report
LEFT OUTER JOIN (
    naicsreport
    JOIN
        naics
        ON naics.id = naicsreport.naics_id)
    ON report.id = naicsreport.report_id
WHERE report.id IN (
  '0000dad2-a7ad-5887-b87d-13fedcd6f854'::UUID,
  '005c88b7-49f7-57c9-8099-53370fb91579'::UUID,
  '1d6cc39d-0bb3-5ee3-ab40-96a066c00d46'::UUID,
  '36a96ce6-811f-5716-ab5c-c63da238e16e'::UUID
)
ORDER BY report.id, naics.code
```

```json
[
  {
    "id": "0000dad2-a7ad-5887-b87d-13fedcd6f854",
    "company": "Scale AI, Inc.",
    "company_id": "2c3ea871-ae2e-590f-ae9f-e0dfaea3531e",
    "state": "CA",
    "location": null,
    "reported": "2023-01-09T00:00:00-08:00",
    "starting": "2023-03-31T00:00:00-07:00",
    "employees": 2,
    "action": "Layoff Permanent",
    "url": "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn-report-for-7-1-2022-to-06-30-2023.pdf",
    "naics": []
  },
  {
    "id": "005c88b7-49f7-57c9-8099-53370fb91579",
    "company": "DIAMOND EXTERIORS INC",
    "company_id": "6daa3c95-36ee-5166-96e9-6b0a8a71c534",
    "state": "IL",
    "location": "WOODSTOCK",
    "reported": "2000-02-25T00:00:00-06:00",
    "starting": null,
    "employees": 78,
    "action": "Plant Closure",
    "url": "https://dceo.illinois.gov/workforcedevelopment/warn.html",
    "naics": [
      {
        "id": 238160,
        "code": "238160",
        "title": "Roofing Contractors"
      },
      {
        "id": 238170,
        "code": "238170",
        "title": "Siding Contractors"
      },
      {
        "id": 238390,
        "code": "238390",
        "title": "Other Building Finishing Contractors"
      },
      {
        "id": 314999,
        "code": "314999",
        "title": "All Other Miscellaneous Textile Product Mills"
      },
      {
        "id": 315210,
        "code": "315210",
        "title": "Cut and Sew Apparel Contractors"
      },
      {
        "id": 315990,
        "code": "315990",
        "title": "Apparel Accessories and Other Apparel Manufacturing"
      }
    ]
  },
  {
    "id": "1d6cc39d-0bb3-5ee3-ab40-96a066c00d46",
    "company": "Walmart",
    "company_id": "d6a0f94f-47d7-5cbb-a788-05df3bb543e0",
    "state": "CA",
    "location": "850 Cherry Avenue  San Bruno CA 94066",
    "reported": "2024-05-17T00:00:00-07:00",
    "starting": "2024-08-09T00:00:00-07:00",
    "employees": 388,
    "action": "Layoff Permanent",
    "url": "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx",
    "naics": []
  },
  {
    "id": "36a96ce6-811f-5716-ab5c-c63da238e16e",
    "company": "Walmart Inc.",
    "company_id": "d6a0f94f-47d7-5cbb-a788-05df3bb543e0",
    "state": "IL",
    "location": "Chicago",
    "reported": "2023-04-28T00:00:00-05:00",
    "starting": null,
    "employees": 439,
    "action": "Layoff",
    "url": "https://dceo.illinois.gov/workforcedevelopment/warn.html",
    "naics": [
      {
        "id": 445110,
        "code": "445110",
        "title": "Supermarkets and Other Grocery Retailers (except Convenience Retailers)"
      },
      {
        "id": 455110,
        "code": "455110",
        "title": "Department Stores"
      }
    ]
  }
]
```

### Join naics on self company_norm

```sql
SELECT
    report.id,
    report.company,
    report.company_norm,
    report.reported,
    report.state,
    report.created,
    report.location,
    report.starting,
    report.employees,
    report.action,
    report.url,
    report2.id AS report2_id,
    report2.company AS report2_company,
    report2.company_norm AS report2_company_norm,
    naics.id AS naics_id,
    naics.code,
    naics.title
FROM report
JOIN
    report AS report2
    ON report.company_norm = report2.company_norm
LEFT OUTER JOIN
    (naicsreport JOIN naics ON naics.id = naicsreport.naics_id)
    ON report2.id = naicsreport.report_id
WHERE report.id IN (
  '0000dad2-a7ad-5887-b87d-13fedcd6f854'::UUID,
  '005c88b7-49f7-57c9-8099-53370fb91579'::UUID,
  '1d6cc39d-0bb3-5ee3-ab40-96a066c00d46'::UUID,
  '36a96ce6-811f-5716-ab5c-c63da238e16e'::UUID
)
ORDER BY report.id, naics.code
```

```json
[
  {
    "id": "0000dad2-a7ad-5887-b87d-13fedcd6f854",
    "company": "Scale AI, Inc.",
    "company_id": "2c3ea871-ae2e-590f-ae9f-e0dfaea3531e",
    "state": "CA",
    "location": null,
    "reported": "2023-01-09T00:00:00-08:00",
    "starting": "2023-03-31T00:00:00-07:00",
    "employees": 2,
    "action": "Layoff Permanent",
    "url": "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn-report-for-7-1-2022-to-06-30-2023.pdf",
    "naics": []
  },
  {
    "id": "005c88b7-49f7-57c9-8099-53370fb91579",
    "company": "DIAMOND EXTERIORS INC",
    "company_id": "6daa3c95-36ee-5166-96e9-6b0a8a71c534",
    "state": "IL",
    "location": "WOODSTOCK",
    "reported": "2000-02-25T00:00:00-06:00",
    "starting": null,
    "employees": 78,
    "action": "Plant Closure",
    "url": "https://dceo.illinois.gov/workforcedevelopment/warn.html",
    "naics": [
      {
        "id": 238160,
        "code": "238160",
        "title": "Roofing Contractors"
      },
      {
        "id": 238170,
        "code": "238170",
        "title": "Siding Contractors"
      },
      {
        "id": 238390,
        "code": "238390",
        "title": "Other Building Finishing Contractors"
      },
      {
        "id": 314999,
        "code": "314999",
        "title": "All Other Miscellaneous Textile Product Mills"
      },
      {
        "id": 315210,
        "code": "315210",
        "title": "Cut and Sew Apparel Contractors"
      },
      {
        "id": 315990,
        "code": "315990",
        "title": "Apparel Accessories and Other Apparel Manufacturing"
      }
    ]
  },
  {
    "id": "1d6cc39d-0bb3-5ee3-ab40-96a066c00d46",
    "company": "Walmart",
    "company_id": "d6a0f94f-47d7-5cbb-a788-05df3bb543e0",
    "state": "CA",
    "location": "850 Cherry Avenue  San Bruno CA 94066",
    "reported": "2024-05-17T00:00:00-07:00",
    "starting": "2024-08-09T00:00:00-07:00",
    "employees": 388,
    "action": "Layoff Permanent",
    "url": "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx",
    "naics": [
      {
        "id": 339115,
        "code": "339115",
        "title": "Ophthalmic Goods Manufacturing"
      },
      {
        "id": 423990,
        "code": "423990",
        "title": "Other Miscellaneous Durable Goods Merchant Wholesalers"
      },
      {
        "id": 44,
        "code": "44-45",
        "title": "Retail Trade"
      },
      {
        "id": 45,
        "code": "44-45",
        "title": "Retail Trade"
      },
      {
        "id": 445110,
        "code": "445110",
        "title": "Supermarkets and Other Grocery Retailers (except Convenience Retailers)"
      },
      {
        "id": 455110,
        "code": "455110",
        "title": "Department Stores"
      },
      {
        "id": 493110,
        "code": "493110",
        "title": "General Warehousing and Storage"
      },
      {
        "id": 54,
        "code": "54",
        "title": "Professional, Scientific, and Technical Services"
      }
    ]
  },
  {
    "id": "36a96ce6-811f-5716-ab5c-c63da238e16e",
    "company": "Walmart Inc.",
    "company_id": "d6a0f94f-47d7-5cbb-a788-05df3bb543e0",
    "state": "IL",
    "location": "Chicago",
    "reported": "2023-04-28T00:00:00-05:00",
    "starting": null,
    "employees": 439,
    "action": "Layoff",
    "url": "https://dceo.illinois.gov/workforcedevelopment/warn.html",
    "naics": [
      {
        "id": 339115,
        "code": "339115",
        "title": "Ophthalmic Goods Manufacturing"
      },
      {
        "id": 423990,
        "code": "423990",
        "title": "Other Miscellaneous Durable Goods Merchant Wholesalers"
      },
      {
        "id": 44,
        "code": "44-45",
        "title": "Retail Trade"
      },
      {
        "id": 45,
        "code": "44-45",
        "title": "Retail Trade"
      },
      {
        "id": 445110,
        "code": "445110",
        "title": "Supermarkets and Other Grocery Retailers (except Convenience Retailers)"
      },
      {
        "id": 455110,
        "code": "455110",
        "title": "Department Stores"
      },
      {
        "id": 493110,
        "code": "493110",
        "title": "General Warehousing and Storage"
      },
      {
        "id": 54,
        "code": "54",
        "title": "Professional, Scientific, and Technical Services"
      }
    ]
  }
]
```

