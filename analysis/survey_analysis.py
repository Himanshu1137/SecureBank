#!/usr/bin/env python3
"""Analysis of the SecureBank user-acceptance survey (Chapter 3.9, Equations 3.5-3.8, Tables 4.10-4.12).

Usage:
    python survey_analysis.py responses.csv            # main analysis
    python survey_analysis.py responses.csv experts.csv  # also content validity ratios (Equation 3.7)

responses.csv  - one row per respondent, columns exactly as in responses_template.csv
experts.csv    - one row per item, one column per expert with values E, U or N (see Appendix A-3)

Only the Python standard library is required. If SciPy is installed, exact t-distribution values are used;
otherwise a close approximation is used and the output says so.
"""
import csv
import math
import statistics as st
import sys
from collections import Counter

BANDS = [(1.00, 1.80, 'Strongly disagree'), (1.81, 2.60, 'Disagree'), (2.61, 3.40, 'Neutral'), (3.41, 4.20, 'Agree'), (4.21, 5.00, 'Strongly agree')]
CONSTRUCTS = {'Perceived usefulness': [f'PU{i}' for i in range(1, 5)], 'Perceived ease of use': [f'PE{i}' for i in range(1, 5)],
              'Trust and security perception': [f'TS{i}' for i in range(1, 6)], 'Intention to use': [f'IU{i}' for i in range(1, 4)]}
SUS_COLS = [f'SUS{i}' for i in range(1, 11)]
try:
    from scipy import stats as _sp
except Exception:  # SciPy is optional
    _sp = None


def interpret(mean):
    for lo, hi, name in BANDS:
        if lo - 0.005 <= mean <= hi + 0.005:
            return name
    return 'out of range'


def t_crit(df, p=0.975):
    if _sp:
        return _sp.t.ppf(p, df)
    z = st.NormalDist().inv_cdf(p)  # Cornish-Fisher expansion of the t quantile
    return z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)


def p_two_sided(t, df):
    if _sp:
        return 2 * (1 - _sp.t.cdf(abs(t), df))
    return 2 * (1 - st.NormalDist().cdf(abs(t) * (1 - 1 / (4 * df))))  # normal approximation


def sus_score(row):
    odd = sum(int(row[f'SUS{i}']) - 1 for i in (1, 3, 5, 7, 9))
    even = sum(5 - int(row[f'SUS{i}']) for i in (2, 4, 6, 8, 10))
    return 2.5 * (odd + even)


def cronbach_alpha(rows, cols):
    k = len(cols)
    if k < 2 or len(rows) < 2:
        return float('nan')
    item_var = [st.variance([float(r[c]) for r in rows]) for c in cols]
    total_var = st.variance([sum(float(r[c]) for c in cols) for r in rows])
    return float('nan') if total_var == 0 else (k / (k - 1)) * (1 - sum(item_var) / total_var)


def table(title, header, body):
    print(f'\n{title}')
    w = [max(len(str(x)) for x in col) for col in zip(header, *body)]
    line = '  '.join(str(h).ljust(w[i]) for i, h in enumerate(header)); print(line); print('-' * len(line))
    for r in body:
        print('  '.join(str(c).ljust(w[i]) for i, c in enumerate(r)))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1], newline='', encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if any((v or '').strip() for v in r.values())]
    n = len(rows)
    if n == 0:
        sys.exit('No responses found in the file.')
    # ---- validation ----
    bad = []
    for i, r in enumerate(rows, 2):
        for c in SUS_COLS + sum(CONSTRUCTS.values(), []):
            try:
                if not 1 <= int(r[c]) <= 5:
                    raise ValueError
            except (KeyError, ValueError):
                bad.append(f'row {i}: column {c} must be an integer from 1 to 5')
    if bad:
        sys.exit('Please fix the following before analysis:\n  ' + '\n  '.join(bad[:25]))
    print(f'SecureBank survey analysis  |  respondents: {n}' + ('' if _sp else '  |  SciPy not found: t values are approximate'))

    # ---- Table 4.10 profile ----
    body = []
    for var, label in (('role', 'Role'), ('age_group', 'Age group'), ('gender', 'Gender'), ('usage', 'Use of UPI / mobile banking')):
        cnt = Counter((r.get(var) or 'no answer').strip() for r in rows)
        for j, (cat, f_) in enumerate(sorted(cnt.items())):
            body.append([label if j == 0 else '', cat, f_, f'{f_ / n * 100:.1f}'])
    table('Table 4.10  Profile of respondents', ['Variable', 'Category', 'f', '%'], body)

    # ---- Table 4.11 SUS ----
    scores = [sus_score(r) for r in rows]
    body = [[c, f'{st.mean(int(r[c]) for r in rows):.2f}', f'{st.stdev(int(r[c]) for r in rows):.2f}' if n > 1 else 'n/a'] for c in SUS_COLS]
    table('Table 4.11  System Usability Scale: item means (1-5)', ['Item', 'Mean', 'SD'], body)
    m = st.mean(scores)
    print(f'\nSUS score (0-100):  mean = {m:.1f}   median = {st.median(scores):.1f}   min = {min(scores):.1f}   max = {max(scores):.1f}')
    if n > 1:
        s = st.stdev(scores); se = s / math.sqrt(n); tc = t_crit(n - 1); t = (m - 68) / se
        print(f'SD = {s:.1f};  95% CI of the mean = [{m - tc * se:.1f}, {m + tc * se:.1f}]')
        print(f'One-sample t test against 68 (Equation 3.8): t({n - 1}) = {t:.2f}, p = {p_two_sided(t, n - 1):.4f}  ->  ' +
              ('mean is significantly different from 68 at the .05 level' if p_two_sided(t, n - 1) < 0.05 else 'no significant difference from 68 at the .05 level'))
        print('H6 (mean SUS at least 68):', 'SUPPORTED' if m >= 68 else 'NOT SUPPORTED', '(point estimate; read together with the confidence interval)')
        if n < 15:
            print('Note: with fewer than 15 respondents treat these results as exploratory.')
    else:
        print('Only one respondent: no SD, confidence interval or test can be computed.')

    # ---- Table 4.12 constructs ----
    body = []
    for name, cols in CONSTRUCTS.items():
        per = [st.mean(float(r[c]) for c in cols) for r in rows]
        a = cronbach_alpha(rows, cols)
        body.append([name, len(cols), f'{st.mean(per):.2f}', f'{st.stdev(per):.2f}' if n > 1 else 'n/a', 'n/a' if math.isnan(a) else f'{a:.2f}', interpret(st.mean(per))])
    table('Table 4.12  Acceptance constructs (item means averaged per respondent)', ['Construct', 'Items', 'Mean', 'SD', "Cronbach's alpha", 'Interpretation'], body)
    body = [[c, f'{st.mean(float(r[c]) for r in rows):.2f}', interpret(st.mean(float(r[c]) for r in rows))] for cols in CONSTRUCTS.values() for c in cols]
    table('Item means', ['Item', 'Mean', 'Interpretation'], body)
    print("\nCronbach's alpha of at least .70 is taken as acceptable (Nunnally, 1978).")

    # ---- task completion ----
    for t in range(1, 7):
        col = f'T{t}'
        if col in rows[0]:
            cnt = Counter((r[col] or '').strip() for r in rows)
            print(f'{col}: ' + ', '.join(f'{k} = {v}' for k, v in sorted(cnt.items())))

    # ---- optional: content validity ratio ----
    if len(sys.argv) > 2:
        with open(sys.argv[2], newline='', encoding='utf-8') as f:
            rd = csv.reader(f); head = next(rd); data = [r for r in rd if r]
        N = len(head) - 1
        body = []
        for r in data:
            ne = sum(1 for v in r[1:] if v.strip().upper() == 'E'); cvr = (ne - N / 2) / (N / 2)
            body.append([r[0], ne, N, f'{cvr:.2f}'])
        table('Content validity ratio (Equation 3.7)', ['Item', 'Essential', 'Experts', 'CVR'], body)
        print("Compare each CVR with the critical value for N experts in Lawshe's (1975) table; revise or drop items below it.")


if __name__ == '__main__':
    main()
