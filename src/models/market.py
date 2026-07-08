from dataclasses import dataclass, field


@dataclass
class Market:

    market_type: str
    pick: str

    handle: float
    bets: float

    # Calculados
    edge: float = 0
    score: int = 0

    pattern: str = ""
    reason: str = ""

    trend: str = "➡️"

    action: str = ""
    stake: float = 0.0

    priority: str = ""

    components: dict = field(default_factory=dict)


    def to_dict(self):

        return {

            "market": self.market_type,

            "pick": self.pick,

            "handle": self.handle,

            "bets": self.bets,

            "edge": self.edge,

            "score": self.score,

            "pattern": self.pattern,

            "reason": self.reason,

            "trend": self.trend,

            "action": self.action,

            "stake": self.stake,

            "priority": self.priority,

            "components": self.components

        }