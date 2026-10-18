"""Targeted checks for temporal leakage and Elo update semantics."""
import unittest
import pandas as pd
from analyze import rate_matches


def fixtures(rows):
    data = pd.DataFrame(rows, columns=['date', 'home_team', 'away_team', 'home_score', 'away_score', 'neutral'])
    data['date'] = pd.to_datetime(data.date)
    data['tournament'] = 'FIFA World Cup'
    return data


class EloTests(unittest.TestCase):
    def test_neutral_win_updates_next_day_only(self):
        data = fixtures([['2022-11-20', 'A', 'B', 1, 0, True],
                         ['2022-11-21', 'A', 'B', 0, 0, True]])
        result = rate_matches(data)
        self.assertEqual(result.iloc[0].home_expected_score, .5)
        self.assertEqual(result.iloc[1].home_elo, 1510)
        self.assertEqual(result.iloc[1].away_elo, 1490)

    def test_future_result_does_not_change_past_ratings(self):
        data = fixtures([['2022-11-20', 'A', 'B', 1, 0, True],
                         ['2022-11-21', 'A', 'B', 0, 5, True]])
        before = rate_matches(data).iloc[0]
        data.loc[1, 'home_score'] = 10
        pd.testing.assert_series_equal(before, rate_matches(data).iloc[0])

    def test_same_day_order_does_not_change_ratings(self):
        data = fixtures([['2022-11-20', 'A', 'B', 1, 0, True],
                         ['2022-11-20', 'A', 'C', 0, 1, True],
                         ['2022-11-21', 'A', 'B', 0, 0, True]])
        first = rate_matches(data).iloc[-1]
        reordered = rate_matches(data.iloc[[1, 0, 2]]).iloc[-1]
        pd.testing.assert_series_equal(first, reordered)

    def test_home_advantage_and_draw_are_not_upsets(self):
        data = fixtures([['2022-11-20', 'A', 'B', 1, 1, False]])
        row = rate_matches(data).iloc[0]
        self.assertAlmostEqual(row.home_expected_score, 1 / (1 + 10 ** (-100 / 400)))
        self.assertTrue(row.is_draw)
        self.assertFalse(row.is_upset)


if __name__ == '__main__':
    unittest.main()
