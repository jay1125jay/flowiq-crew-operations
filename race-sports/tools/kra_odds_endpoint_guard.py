from pathlib import Path

P = Path('race-sports/tools/kra_official_enricher.py')
BAD = "('KRA_API27_OFFICIAL', 'https://apis.data.go.kr/B551015/API27_1/winPredictionRateInfo_1')"
GOOD = "('KRA_API28_OFFICIAL', 'https://apis.data.go.kr/B551015/API28_1/Dividend_rate')"


def main():
    s = P.read_text(encoding='utf-8')
    changed = False
    if BAD in s:
        s = s.replace(BAD, GOOD, 1)
        changed = True
    if 'API27_1/winPredictionRateInfo_1' in s:
        raise SystemExit('KRA_ODDS_ENDPOINT_GUARD_FAIL:API27_STILL_PRESENT')
    if 'API301/Dividend_rate_total' not in s or 'API28_1/Dividend_rate' not in s:
        raise SystemExit('KRA_ODDS_ENDPOINT_GUARD_FAIL:REQUIRED_ODDS_ENDPOINT_MISSING')
    if changed:
        P.write_text(s, encoding='utf-8')
    print('KRA_ODDS_ENDPOINT_GUARD=' + ('UPDATED_API27_TO_API28' if changed else 'PASS'))


if __name__ == '__main__':
    main()
