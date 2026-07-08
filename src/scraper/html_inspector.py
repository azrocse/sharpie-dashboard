from bs4 import BeautifulSoup
import os
import glob



def find_html_file():

    files = glob.glob(
        "data/raw/draftkings_0_page1_*.html"
    )


    if not files:

        raise FileNotFoundError(
            "No se encontró ningún HTML de DraftKings"
        )


    return files[0]





def inspect_html(file_path):


    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        html = file.read()



    soup = BeautifulSoup(
        html,
        "html.parser"
    )


    print("==============================")
    print("HTML INSPECTOR")
    print("==============================")


    print()

    print("Archivo:")

    print(file_path)


    print()


    tables = soup.find_all(
        "table"
    )


    print(
        "Tablas encontradas:",
        len(tables)
    )


    print()


    for i, table in enumerate(tables):

        print(
            f"--- TABLA {i+1} ---"
        )


        rows = table.find_all(
            "tr"
        )


        print(
            "Filas:",
            len(rows)
        )


        if rows:

            print(
                "Primera fila:"
            )


            print(
                rows[0].get_text(
                    " ",
                    strip=True
                )
            )


        print()



    keywords = [

        "Handle",
        "Bets",
        "Money",
        "Spread",
        "Total",
        "ML"

    ]


    print("Keywords:")


    for keyword in keywords:


        found = soup.find_all(
            string=lambda x:
            x and keyword.lower()
            in x.lower()
        )


        print(
            keyword,
            ":",
            len(found)
        )





if __name__ == "__main__":


    file = find_html_file()


    inspect_html(
        file
    )