from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from pipeline.export import export_all

from dashboard.generate_dashboard import generate_dashboard



def main():


    downloaded = download_all()



    parsed = parse_all(
        downloaded
    )



    analyzed = analyze_all(
        parsed
    )



    export_file = export_all(
        analyzed
    )



    generate_dashboard()



if __name__ == "__main__":

    main()