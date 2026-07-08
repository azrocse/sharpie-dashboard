import json
import os



def load_previous_history(history_file):


    if not os.path.exists(history_file):

        return {}



    with open(
        history_file,
        encoding="utf-8"
    ) as file:

        data = json.load(file)



    previous = {}



    for pick in data.get(
        "picks",
        []
    ):


        key = (

            pick.get("league"),

            pick.get("game"),

            pick.get("market"),

            pick.get("pick")

        )


        previous[key] = pick



    return previous





def calculate_trend(
    current,
    previous
):


    if not previous:


        return {


            "trend":

                "🆕 NUEVO",


            "movement":

                "Sin historial"


        }




    handle_change = (

        current.get(
            "handle",
            0
        )

        -

        previous.get(
            "handle",
            0
        )

    )



    bets_change = (

        current.get(
            "bets",
            0
        )

        -

        previous.get(
            "bets",
            0
        )

    )



    edge_change = (

        current.get(
            "edge",
            0
        )

        -

        previous.get(
            "edge",
            0
        )

    )




    if handle_change >= 5 and edge_change >= 5:


        return {


            "trend":

                "📈 DINERO ENTRANDO",


            "movement":

                f"+{handle_change}% handle"


        }




    if handle_change <= -5:


        return {


            "trend":

                "📉 PERDIENDO FUERZA",


            "movement":

                f"{handle_change}% handle"


        }





    if abs(bets_change) >= 10:


        return {


            "trend":

                "🔄 CAMBIO DE BOLETOS",


            "movement":

                f"{bets_change}% bets"


        }





    return {


        "trend":

            "➡️ ESTABLE",


        "movement":

            f"{handle_change}% handle"


    }