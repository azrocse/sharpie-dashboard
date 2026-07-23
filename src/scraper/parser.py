from bs4 import BeautifulSoup
import re

class DraftKingsParser:

    def count_events(self, html):
        soup = BeautifulSoup(html, "html.parser")
        return len(soup.select(".tb-se"))

    def split_game(self, text):
        parts = text.split(" vs ")
        if len(parts) == 2:
            return {
                "away": parts[0].strip(),
                "home": parts[1].strip()
            }
        parts = text.split(" @ ")
        if len(parts) == 2:
            return {
                "away": parts[0].strip(),
                "home": parts[1].strip()
            }
        return {
            "away": text,
            "home": ""
        }

    def parse_file(self, file, league_name):
        with open(file, "r", encoding="utf-8") as f:
            html = f.read()

        soup = BeautifulSoup(html, "html.parser")
        games = []
        events = soup.select(".tb-se")

        print("Eventos encontrados:", len(events))

        for event in events:
            title = event.select_one(".tb-se-title h5")
            time = event.select_one(".tb-se-title span")

            if not title:
                continue

            game_name = title.get_text(" ", strip=True)
            teams = self.split_game(game_name)

            game = {
                "league": league_name,
                "game": game_name,
                "away": teams["away"],
                "home": teams["home"],
                "time_raw": time.get_text(" ", strip=True) if time else "",
                "markets": []
            }

            market_blocks = event.select(".tb-market-wrap > div")

            for block in market_blocks:
                head = block.select_one(".tb-se-head div")
                if not head:
                    continue

                market_name = head.get_text(" ", strip=True)

                # .tb-sm es el CONTENEDOR de ambos lados del mercado, no una fila.
                # Cada lado real vive en .tb-sodd, un nivel mas adentro.
                sm_containers = block.select(".tb-sm")

                for container in sm_containers:
                    rows = container.select(".tb-sodd")

                    for row in rows:
                        pick = row.select_one(".tb-slipline")
                        if not pick:
                            continue

                        text = row.get_text(" ", strip=True)
                        text = text.replace("\u2212", "-")  # DK usa el signo menos unicode (U+2212), no el guion ascii

                        odds_val = "—"
                        line_val = None

                        line_match = re.search(r'([+-]?\d+\.5|\b\d+\.5\b)', text)
                        if line_match:
                            line_val = line_match.group(1)
                            text_remainder = text.replace(line_val, "", 1)
                        else:
                            text_remainder = text

                        odds_match = re.search(r'([+-]\d{2,4}|EVEN)', text_remainder)
                        if odds_match:
                            odds_val = odds_match.group(1)

                        percentages = re.findall(r"(\d+)%", text)

                        if len(percentages) >= 2:
                            handle = int(percentages[0])
                            bets = int(percentages[1])

                            game["markets"].append({
                                "market": market_name,
                                "pick": pick.get_text(" ", strip=True),
                                "line": line_val,
                                "odds": odds_val,
                                "handle": handle,
                                "bets": bets,
                                "edge": handle - bets
                            })
            games.append(game)

        return {
            "league": league_name,
            "games": games
        }