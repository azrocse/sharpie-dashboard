from parser import DraftKingsParser
import json
import requests
from bs4 import BeautifulSoup


url = (
    "https://dknetwork.draftkings.com/"
    "draftkings-sportsbook-betting-splits/"
    "?tb_eg=84240"
    "&tb_edate=today"
    "&tb_page=2"
)


html = requests.get(
    url,
    headers={
        "User-Agent":
        "Mozilla/5.0"
    }
).text



file = "data/raw/mlb_test.html"


with open(
    file,
    "w",
    encoding="utf-8"
) as f:

    f.write(html)



parser = DraftKingsParser()


data = parser.parse_file(
    file
)


print(
    json.dumps(
        data[:2],
        indent=4,
        ensure_ascii=False
    )
)