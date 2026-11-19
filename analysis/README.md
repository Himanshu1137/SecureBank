# Survey analysis (Chapter 4.1.6)

1. Collect responses with the questionnaire in Appendix A-2 of the thesis (e.g. a Google Form) and export them in the format of `responses_template.csv`
   (one row per respondent; SUS and acceptance items as whole numbers 1-5).
2. Run `python survey_analysis.py responses.csv` - it prints the numbers for Tables 4.10, 4.11 and 4.12, the SUS score with its 95% confidence interval and the t test against 68.
3. For expert validation (Appendix A-3) fill `experts_template.csv` with E / U / N and run `python survey_analysis.py responses.csv experts.csv`.

Only the Python standard library is needed (SciPy is used if installed). Do not put invented data into the thesis tables.
