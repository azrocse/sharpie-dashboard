from bs4 import BeautifulSoup
import glob



def get_file():

    files = glob.glob(
        "data/raw/draftkings_0_page1_*.html"
    )

    if not files:
        raise Exception(
            "No hay HTML disponible"
        )

    return files[0]





def inspect_context(file):


    with open(
        file,
        "r",
        encoding="utf-8"
    ) as f:

        html = f.read()



    soup = BeautifulSoup(
        html,
        "html.parser"
    )


    print("==============================")
    print("CONTEXT INSPECTOR")
    print("==============================")


    texts = soup.find_all(
        string=lambda x:
        x and "Handle" in x
    )


    print(
        "Encontrados:",
        len(texts)
    )


    for i, text in enumerate(texts[:5]):


        print()

        print(
            "---- CASO",
            i+1,
            "----"
        )


        parent = text.parent


        print(
            parent.prettify()[:1500]
        )





if __name__ == "__main__":


    file = get_file()


    print(
        "Archivo:",
        file
    )


    inspect_context(
        file
    )