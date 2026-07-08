from parser import DraftKingsParser
import glob
import json



file = glob.glob(
    "data/raw/draftkings_0_page1_*.html"
)[0]



parser = DraftKingsParser()


data = parser.parse_file(
    file
)


print(
    json.dumps(
        data[:3],
        indent=4,
        ensure_ascii=False
    )
)