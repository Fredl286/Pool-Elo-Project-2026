import argparse
import csv
import json
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "results.csv"
DEFAULT_TEMPLATE = BASE_DIR / "leaderboard_template.html"
DEFAULT_OUTPUT = BASE_DIR / "leaderboard.html"
REQUIRED_COLUMNS = {
    "date",
    "season",
    "division",
    "match_number",
    "game_number",
    "winner_id",
    "winner_name",
    "loser_id",
    "loser_name",
}


def parse_result_date(value):
    value = value.strip()
    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            pass
    raise ValueError(f"unsupported date format: {value!r}")


def load_games(input_path):
    games = []
    skipped_doubles = 0
    skipped_invalid = 0

    with input_path.open("r", newline="", encoding="utf-8-sig") as input_file:
        reader = csv.DictReader(input_file)
        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing_columns))}")

        for row_number, row in enumerate(reader, start=2):
            winner_id = row["winner_id"].strip()
            loser_id = row["loser_id"].strip()
            winner_name = row["winner_name"].strip()
            loser_name = row["loser_name"].strip()
            if ";" in winner_id or ";" in loser_id or ";" in winner_name or ";" in loser_name:
                skipped_doubles += 1
                continue
            if not all((winner_id, loser_id, winner_name, loser_name)) or winner_id == loser_id:
                skipped_invalid += 1
                continue

            try:
                game_date = parse_result_date(row["date"])
                season = int(row["season"])
                division = int(row["division"])
                match_number = int(row["match_number"])
                game_number = int(row["game_number"])
            except (TypeError, ValueError):
                skipped_invalid += 1
                continue

            games.append(
                {
                    "date": game_date,
                    "season": season,
                    "division": division,
                    "match_number": match_number,
                    "game_number": game_number,
                    "source_order": row_number,
                    "winner_id": winner_id,
                    "winner_name": winner_name,
                    "loser_id": loser_id,
                    "loser_name": loser_name,
                }
            )

    games.sort(
        key=lambda game: (
            game["date"],
            game["season"],
            game["division"],
            game["match_number"],
            game["game_number"],
            game["source_order"],
        )
    )
    return games, skipped_doubles, skipped_invalid


def calculate_ratings(games, initial_rating, k_factor, provisional_games, seed_ratings=None):
    players = {}
    seed_ratings = seed_ratings or {}

    def get_player(player_id, name):
        if player_id not in players:
            start_rating = seed_ratings.get(player_id, initial_rating)
            players[player_id] = {
                "id": player_id,
                "name": name,
                "rating": start_rating,
                "peak_rating": start_rating,
                "wins": 0,
                "losses": 0,
                "games": 0,
                "last_played": "",
                "history": [],
            }
        player = players[player_id]
        player["name"] = name
        return player

    for game in games:
        winner = get_player(game["winner_id"], game["winner_name"])
        loser = get_player(game["loser_id"], game["loser_name"])
        winner_before = winner["rating"]
        loser_before = loser["rating"]
        expected_winner = 1 / (1 + 10 ** ((loser_before - winner_before) / 400))
        rating_change = k_factor * (1 - expected_winner)
        game_date = game["date"].isoformat()

        winner["rating"] = winner_before + rating_change
        loser["rating"] = loser_before - rating_change
        winner["wins"] += 1
        loser["losses"] += 1
        winner["games"] += 1
        loser["games"] += 1
        winner["last_played"] = game_date
        loser["last_played"] = game_date
        winner["peak_rating"] = max(winner["peak_rating"], winner["rating"])
        loser["peak_rating"] = max(loser["peak_rating"], loser["rating"])
        winner["history"].append(
            [game_date, loser["name"], "W", round(winner_before, 1), round(loser_before, 1), round(rating_change, 1), round(winner["rating"], 1)]
        )
        loser["history"].append(
            [game_date, winner["name"], "L", round(loser_before, 1), round(winner_before, 1), round(-rating_change, 1), round(loser["rating"], 1)]
        )

    histories = {player_id: player.pop("history") for player_id, player in players.items()}

    leaderboard = sorted(
        players.values(),
        key=lambda player: (-player["rating"], -player["games"], player["name"].casefold()),
    )
    for rank, player in enumerate(leaderboard, start=1):
        player["rank"] = rank
        player["provisional"] = player["games"] < provisional_games
        for key in ("rating", "peak_rating"):
            player[key] = round(player[key], 1)

    return leaderboard, histories


def build_page(template_path, output_path, leaderboard, histories, games, initial_rating, k_factor, provisional_games):
    template = template_path.read_text(encoding="utf-8")
    latest_date = games[-1]["date"] if games else None
    earliest_date = games[0]["date"] if games else None
    payload = {
        "players": leaderboard,
        "history": histories,
        "summary": {
            "players": len(leaderboard),
            "games": len(games),
            "latest_date": latest_date.isoformat() if latest_date else "",
            "earliest_date": earliest_date.isoformat() if earliest_date else "",
            "top_rating": leaderboard[0]["rating"] if leaderboard else initial_rating,
            "initial_rating": initial_rating,
            "k_factor": k_factor,
            "provisional_games": provisional_games,
        },
    }
    embedded_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    embedded_data = (
        embedded_data.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template.replace("__LEADERBOARD_DATA__", embedded_data), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Replay pool results with Elo and build the leaderboard page.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Results CSV from scraper.py")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Generated HTML leaderboard")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="HTML page template")
    parser.add_argument("--initial-rating", type=float, default=1000)
    parser.add_argument("--k-factor", type=float, default=32)
    parser.add_argument("--provisional-games", type=int, default=20)
    parser.add_argument(
        "--warmup-passes",
        type=int,
        default=0,
        help=(
            "Replay the full match history this many times beforehand, seeding each "
            "pass with the previous pass's final ratings, to reduce the 1000-start bias."
        ),
    )
    args = parser.parse_args()

    if args.initial_rating <= 0 or args.k_factor <= 0 or args.provisional_games < 1:
        parser.error("ratings and K-factor must be positive; provisional-games must be at least 1")
    if args.warmup_passes < 0:
        parser.error("warmup-passes must be zero or a positive integer")

    try:
        games, skipped_doubles, skipped_invalid = load_games(args.input)

        seed_ratings = None
        for _ in range(args.warmup_passes):
            warm_leaderboard, _ = calculate_ratings(
                games,
                args.initial_rating,
                args.k_factor,
                args.provisional_games,
                seed_ratings=seed_ratings,
            )
            seed_ratings = {player["id"]: player["rating"] for player in warm_leaderboard}

        leaderboard, histories = calculate_ratings(
            games,
            args.initial_rating,
            args.k_factor,
            args.provisional_games,
            seed_ratings=seed_ratings,
        )
        build_page(
            args.template,
            args.output,
            leaderboard,
            histories,
            games,
            args.initial_rating,
            args.k_factor,
            args.provisional_games,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(f"Processed {len(games):,} singles games across {len(leaderboard):,} players.")
    if skipped_doubles or skipped_invalid:
        print(f"Skipped {skipped_doubles:,} doubles and {skipped_invalid:,} invalid rows.")
    if games:
        print(f"Chronological range: {games[0]['date']:%d/%m/%Y} to {games[-1]['date']:%d/%m/%Y}.")
    print(f"Wrote leaderboard to {args.output}")


if __name__ == "__main__":
    main()