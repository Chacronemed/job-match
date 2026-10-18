"""Static dashboard: a JSON snapshot of the DB and one self-contained HTML page.

`data.build_dashboard_data` decides what leaves the database (an allow-list: no descriptions,
no search keywords, no profile, no addresses). `render.write_site` writes `index.html` and
`data.json` into a directory that a static host serves as-is.
"""
