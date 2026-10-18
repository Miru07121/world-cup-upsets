"""Historical, pre-match Elo exploration; not official FIFA rankings or betting odds."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'data/results_through_2022.csv'


def load_matches():
    raw = pd.read_csv(SOURCE, parse_dates=['date'])
    required = ['date', 'home_team', 'away_team', 'home_score', 'away_score', 'tournament', 'neutral']
    if raw[required].isna().any().any():
        raise ValueError('Missing required match values')
    if not raw.neutral.isin([True, False]).all():
        raise ValueError('Unexpected neutral-ground values')
    scores = raw[['home_score', 'away_score']]
    if (scores < 0).any().any() or (scores % 1 != 0).any().any():
        raise ValueError('Scores must be nonnegative integers')
    if (raw.home_team == raw.away_team).any():
        raise ValueError('A team cannot play itself')
    # No kickoff times are supplied. Quarantine every repeated date/team key.
    ambiguous = raw.duplicated(['date', 'home_team', 'away_team'], keep=False)
    clean = raw.loc[~ambiguous & raw.date.le('2022-12-31')].sort_values('date', kind='stable')
    return raw, clean, raw.loc[ambiguous]


def rate_matches(matches, k=20, home_advantage=100):
    ratings = defaultdict(lambda: 1500.0)
    records = []
    # All matches on a date use ratings from the start of that date. This avoids
    # arbitrary source-row order affecting same-day pre-match features.
    for date, day in matches.groupby('date', sort=True):
        changes = defaultdict(float)
        for row in day.itertuples(index=False):
            home, away = ratings[row.home_team], ratings[row.away_team]
            gap = home - away + (0 if row.neutral else home_advantage)
            expected = 1 / (1 + 10 ** (-gap / 400))
            actual = 1.0 if row.home_score > row.away_score else (0.0 if row.home_score < row.away_score else 0.5)
            change = k * (actual - expected)
            changes[row.home_team] += change
            changes[row.away_team] -= change
            if row.tournament == 'FIFA World Cup' and 1998 <= date.year <= 2022:
                winner = row.home_team if actual == 1 else (row.away_team if actual == 0 else '')
                upset = (actual == 1 and gap < 0) or (actual == 0 and gap > 0)
                records.append({'date': date.strftime('%Y-%m-%d'), 'year': date.year,
                                'home_team': row.home_team, 'away_team': row.away_team,
                                'home_score': row.home_score, 'away_score': row.away_score,
                                'neutral': row.neutral, 'home_elo': home, 'away_elo': away,
                                'adjusted_home_gap': gap, 'home_expected_score': expected,
                                'home_actual_score': actual, 'winner': winner,
                                'is_draw': actual == .5, 'is_upset': upset,
                                'absolute_gap': abs(gap),
                                'is_major_upset': upset and abs(gap) >= 150})
        if not np.isclose(sum(changes.values()), 0, atol=1e-8):
            raise ValueError('Elo updates must be zero-sum')
        for team, change in changes.items():
            ratings[team] += change
    return pd.DataFrame(records)


def main():
    raw, clean, excluded = load_matches()
    out = ROOT / 'results'
    out.mkdir(exist_ok=True)
    excluded.to_csv(out / 'excluded_ambiguous_matches.csv', index=False)
    rated = rate_matches(clean)
    counts = rated.groupby('year').size()
    if counts.to_dict() != {year: 64 for year in range(1998, 2023, 4)}:
        raise ValueError('Expected seven complete 64-match World Cups')
    rated.to_csv(out / 'world_cup_match_ratings.csv', index=False)
    upsets = rated.loc[rated.is_upset].sort_values('absolute_gap', ascending=False)
    upsets.to_csv(out / 'ranked_upsets.csv', index=False)
    yearly = rated.groupby('year').agg(matches=('year', 'size'), draws=('is_draw', 'sum'),
                                      underdog_wins=('is_upset', 'sum'), major_upsets=('is_major_upset', 'sum'))
    yearly['decisive_matches'] = yearly.matches - yearly.draws
    yearly['underdog_win_pct_all_matches'] = yearly.underdog_wins / yearly.matches * 100
    yearly['underdog_win_pct_decisive_matches'] = yearly.underdog_wins / yearly.decisive_matches * 100
    yearly.to_csv(out / 'tournament_summary.csv')
    sensitivity = []
    for k, home in [(20, 0), (20, 100), (40, 0), (40, 100)]:
        case = rated if (k, home) == (20, 100) else rate_matches(clean, k, home)
        for threshold in [100, 150, 200]:
            opportunities = case.absolute_gap.ge(threshold)
            sensitivity.append({'k': k, 'home_advantage': home, 'gap_threshold': threshold,
                                'all_underdog_wins': int(case.is_upset.sum()),
                                'major_underdog_opportunities': int(opportunities.sum()),
                                'major_upsets': int((opportunities & case.is_upset).sum())})
    pd.DataFrame(sensitivity).to_csv(out / 'sensitivity.csv', index=False)
    top = upsets.iloc[0]
    summary = {'period': '1998–2022 men’s FIFA World Cup finals',
               'input_rows': len(raw), 'excluded_ambiguous_rows': len(excluded),
               'historical_matches_used': len(clean), 'world_cup_matches': len(rated),
               'draws_including_shootouts': int(rated.is_draw.sum()),
               'underdog_wins': int(rated.is_upset.sum()),
               'underdog_win_pct_all_matches': float(rated.is_upset.mean() * 100),
               'underdog_win_pct_decisive_matches': float(rated.is_upset.sum() / (~rated.is_draw).sum() * 100),
               'major_upsets_150_points': int(rated.is_major_upset.sum()),
               'major_underdog_opportunities_150_points': int(rated.absolute_gap.ge(150).sum()),
               'largest_upset': top[['date', 'home_team', 'away_team', 'home_score', 'away_score', 'winner', 'absolute_gap']].to_dict(),
               'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, ax = plt.subplots(figsize=(10, 6), layout='constrained')
    shown = upsets.head(10).iloc[::-1]
    labels = [f'{r.year}: {r.home_team} {r.home_score:.0f}–{r.away_score:.0f} {r.away_team}' for r in shown.itertuples()]
    ax.barh(labels, shown.absolute_gap, color='#147d92')
    ax.set(xlabel='Pre-match Elo disadvantage of winning team (venue-adjusted)',
           title='Biggest World Cup upsets, 1998–2022\nCustom Elo · K=20 · home advantage=100 · penalties excluded')
    fig.get_layout_engine().set(rect=(0, .055, 1, .945))
    fig.text(.99, .01, 'Results: Mart Jürisoo / international_results; ratings: this project', ha='right', fontsize=8)
    fig.savefig(out / 'biggest_upsets.png', dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 5), layout='constrained')
    bars = ax.bar(yearly.index.astype(str), yearly.underdog_win_pct_all_matches, color='#147d92')
    ax.bar_label(bars, labels=[f'{v}/64' for v in yearly.underdog_wins], padding=3)
    ax.set(ylim=(0, max(yearly.underdog_win_pct_all_matches) + 8), ylabel='Underdog wins / all matches (%)',
           title='How often did the lower-rated team win?\nDraws and shootouts remain in the denominator')
    fig.get_layout_engine().set(rect=(0, .055, 1, .945))
    fig.text(.99, .01, 'Results: Mart Jürisoo / international_results; custom Elo model', ha='right', fontsize=8)
    fig.savefig(out / 'upset_rate_by_tournament.png', dpi=160)
    plt.close(fig)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
