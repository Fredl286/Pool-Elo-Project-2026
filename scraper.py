import argparse
import csv
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.meltonpool.uk/division.php"
CSV_FIELDS = [
    "season",
    "division",
    "date",
    "match_number",
    "game_number",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "winner_team",
    "loser_team",
    "winner_id",
    "winner_name",
    "loser_id",
    "loser_name",
]


def clean_text(element):
    text = " ".join(element.stripped_strings).replace("\xa0", " ").replace("\ufffd", "")
    return " ".join(text.split())


def parse_date(value):
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", value)
    if match:
        _, day, month, year = match.groups()
        parsed = datetime.strptime(f"{day} {month} {year}", "%d %B %Y")
        return parsed.strftime("%d/%m/%Y")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return value.strip()


def get_players(cell):
    players = []
    for link in cell.select('a[href*="player.php"]'):
        query = parse_qs(urlparse(link.get("href", "")).query)
        player_id = query.get("id", [None])[0]
        if player_id:
            players.append({"id": player_id, "name": clean_text(link)})
    return players


def flatten_players(players, field):
    return "; ".join(player[field] for player in players)


def parse_results(html, division, season):
    soup = BeautifulSoup(html, "html.parser")
    results_table = soup.select_one("table.results-table")
    if results_table is None:
        return []

    rows = results_table.select("tbody > tr")
    results = []
    current_date = ""
    match_number = 0

    for index, row in enumerate(rows):
        heading = row.select_one("th.section-heading h4")
        if heading:
            current_date = parse_date(clean_text(heading))
            continue

        cells = row.find_all("td", recursive=False)
        if len(cells) != 7 or index + 1 >= len(rows):
            continue

        details = rows[index + 1].select_one("td.match-details table")
        if details is None:
            continue

        home_team = clean_text(cells[1].select_one("h4") or cells[1])
        away_team = clean_text(cells[5].select_one("h4") or cells[5])
        home_score_text = clean_text(cells[2])
        away_score_text = clean_text(cells[4])
        if not home_score_text.isdigit() or not away_score_text.isdigit():
            continue

        match_number += 1
        game_number = 0
        for game_row in details.select("tr"):
            winner_cell = game_row.select_one("td.frame-winner.player-left, td.frame-winner.player-right")
            loser_cell = game_row.select_one("td.frame-loser.player-left, td.frame-loser.player-right")
            if winner_cell is None or loser_cell is None:
                continue

            winner_players = get_players(winner_cell)
            loser_players = get_players(loser_cell)
            if not winner_players or not loser_players:
                continue

            game_number += 1
            if len(winner_players) != 1 or len(loser_players) != 1:
                continue

            winner_is_home = "player-left" in winner_cell.get("class", [])
            results.append(
                {
                    "season": season,
                    "division": division,
                    "date": current_date,
                    "match_number": match_number,
                    "game_number": game_number,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_score": int(home_score_text),
                    "away_score": int(away_score_text),
                    "winner_team": home_team if winner_is_home else away_team,
                    "loser_team": away_team if winner_is_home else home_team,
                    "winner_id": flatten_players(winner_players, "id"),
                    "winner_name": flatten_players(winner_players, "name"),
                    "loser_id": flatten_players(loser_players, "id"),
                    "loser_name": flatten_players(loser_players, "name"),
                }
            )

    return results


def get_available_divisions(html, season, max_division):
    soup = BeautifulSoup(html, "html.parser")
    divisions = set()
    for link in soup.select('a[href*="division.php"]'):
        query = parse_qs(urlparse(link.get("href", "")).query)
        linked_season = query.get("season", [None])[0]
        if linked_season is not None and linked_season != str(season):
            continue
        division = query.get("division", [None])[0]
        if division and division.isdigit() and 1 <= int(division) <= max_division:
            divisions.add(int(division))
    return sorted(divisions)


def fetch_page(session, base_url, division, season):
    response = session.get(
        base_url,
        params={"division": division, "season": season},
        timeout=30,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def scrape(start_season, end_season, max_division, only_division, base_url):
    session = requests.Session()
    session.headers["User-Agent"] = "PoolEloResultsScraper/1.0 (historical league results)"
    all_results = []

    for season in range(start_season, end_season + 1):
        if only_division is None:
            try:
                first_page = fetch_page(session, base_url, 1, season)
            except requests.RequestException as error:
                print(f"Season {season}: could not fetch division 1: {error}")
                continue
            if first_page is None:
                print(f"Season {season}: division 1 page not found; skipping")
                continue
            divisions = get_available_divisions(first_page, season, max_division)
            if not divisions:
                divisions = [1]
            pages = {1: first_page}
        else:
            divisions = [only_division]
            pages = {}

        for division in divisions:
            try:
                html = pages.get(division)
                if html is None:
                    html = fetch_page(session, base_url, division, season)
                if html is None:
                    print(f"Season {season}, division {division}: page not found; skipping")
                    continue
            except requests.RequestException as error:
                print(f"Season {season}, division {division}: request failed: {error}")
                continue

            results = parse_results(html, division, season)
            all_results.extend(results)
            print(f"Season {season}, division {division}: {len(results)} games")

    return all_results


def main():
    parser = argparse.ArgumentParser(description="Scrape Melton Pool League game results into CSV.")
    parser.add_argument("--start-season", type=int, default=1)
    parser.add_argument("--end-season", type=int, default=23)
    parser.add_argument("--max-division", type=int, default=7)
    parser.add_argument("--division", type=int, help="Scrape one division instead of discovering them")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--output", type=Path, default=Path("results.csv"))
    args = parser.parse_args()

    if args.start_season < 1 or args.end_season < args.start_season:
        parser.error("season range must start at 1 or higher and end no earlier than it starts")
    if args.max_division < 1 or (args.division is not None and not 1 <= args.division <= args.max_division):
        parser.error("division values must be between 1 and --max-division")

    results = scrape(
        args.start_season,
        args.end_season,
        args.max_division,
        args.division,
        args.base_url,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print(f"Wrote {len(results)} games to {args.output}")


if __name__ == "__main__":
    main()