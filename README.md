# Melton Pool League — Elo Leaderboard

This project scrapes singles results from the [Melton Pool League](https://www.meltonpool.uk) website, replays every game through an Elo rating system, and publishes the result as a static, self-contained HTML leaderboard.

## How it works

The pipeline has two stages:

1. **`scraper.py`** — crawls the division/results pages on meltonpool.uk and writes every individual game (not just match scores) to [`results.csv`](results.csv), including the date, season, division, match/game number, and the winner/loser player IDs and names.
2. **`build_leaderboard.py`** — reads `results.csv`, replays the games in chronological order through an Elo model, and renders the ratings into [`leaderboard.html`](leaderboard.html) using [`leaderboard_template.html`](leaderboard_template.html) as the page shell.

```
scraper.py  --> results.csv  --> build_leaderboard.py  --> leaderboard.html
                                        ^
                                 leaderboard_template.html
```

Doubles games (rows with multiple players per side) and malformed rows are skipped automatically — only singles games count towards ratings.

## How the Elo rating is calculated

Every player starts at an **initial rating of 1000**. Games are sorted chronologically (by date, season, division, match number, then game number) and replayed one at a time. For each game:

1. Work out the winner's expected chance of winning, based on the ratings gap:

$$E_{winner} = \frac{1}{1 + 10^{(R_{loser} - R_{winner}) / 400}}$$

2. Apply the rating change using the standard Elo update, with a fixed **K-factor of 32**:

$$\Delta = K \times (1 - E_{winner})$$

3. The winner gains $\Delta$ and the loser loses the same $\Delta$ — Elo is zero-sum.

Because the K-factor is constant, a win against a much higher-rated opponent moves your rating more than a win against someone similarly rated or weaker. Every game, win/loss record, peak rating, and rating history is tracked per player so the leaderboard can show a full progression chart, not just the final number.

Players with fewer than **20 games** (`--provisional-games`) are flagged as "provisional" on the leaderboard, since their rating hasn't seen enough results to be reliable yet.

### The cold-start problem, and warm-up passes

Elo's biggest weakness on a finite, historical dataset is that everyone starts at the same 1000 rating — so the *earliest* games in the dataset are judged against opponents whose "true" skill isn't reflected yet, which adds noise to the early history.

To reduce this, `build_leaderboard.py` supports `--warmup-passes N`. This replays the entire match history `N` extra times first (discarding the history each time, keeping only the final rating each player reached), then seeds the real, history-tracked pass with those converged ratings instead of a flat 1000. In practice this lets ratings settle near their steady-state values before the "real" pass runs, and 2–3 passes is normally enough to converge. It's off by default (`--warmup-passes 0`) to preserve the original behaviour.

## Usage

Install dependencies:

```powershell
pip install -r requirements.txt
```

Scrape the latest results:

```powershell
python scraper.py
```

Build the leaderboard:

```powershell
python build_leaderboard.py
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--input` | `results.csv` | Source CSV of games |
| `--output` | `leaderboard.html` | Generated leaderboard page |
| `--template` | `leaderboard_template.html` | HTML page shell the data is embedded into |
| `--initial-rating` | `1000` | Starting Elo for every new player |
| `--k-factor` | `32` | Elo K-factor (size of rating swings) |
| `--provisional-games` | `20` | Games needed before a rating is no longer "provisional" |
| `--warmup-passes` | `0` | Extra convergence passes before the real, history-tracked run (see above) |

Example with warm-up passes:

```powershell
python build_leaderboard.py --warmup-passes 3
```

## Output

`leaderboard.html` is a single static file with the full dataset embedded as JSON — it can be opened directly in a browser or hosted anywhere as a static page, with no server or build step required. It includes:

- A ranked leaderboard with wins/losses, games played, peak rating, and last-played date.
- Search and filtering (by minimum games played, activity in the last year, etc.).
- A per-player history dialog showing every game's rating change over time.
