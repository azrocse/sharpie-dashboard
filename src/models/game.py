from dataclasses import dataclass, field
from typing import List

from models.market import Market


@dataclass
class Game:

    league: str

    date: str

    time_local: str

    away: str

    home: str

    markets: List[Market] = field(default_factory=list)



    def to_dict(self):

        return {

            "league": self.league,

            "date": self.date,

            "time_local": self.time_local,

            "game": f"{self.away} @ {self.home}",

            "markets": [

                market.to_dict()

                for market in self.markets

            ]

        }