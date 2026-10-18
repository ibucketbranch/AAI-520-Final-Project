# Notebooks

**Overview:** logic lives in `src/`, notebooks import it. Install the package first (`make setup`, or `pip install -e .` in Colab). The news chain also needs spaCy's English model: `make setup` downloads it, or run `python -m spacy download en_core_web_sm`.

## Rules

- Dev notebooks go under `notebooks/dev/`, named `<initials>_<topic>.ipynb` (for example `mv_planner_probe.ipynb`).
- Outputs are stripped on commit by nbstripout; CI fails any dev notebook that still carries outputs. Dev notebooks are never merged into each other.
- The single final notebook under `notebooks/final/` is assembled in the last week from the package and is the only notebook that keeps outputs (Kahila, Sep 11: one combined notebook; HTML is acceptable; comments stay in the notebook even with a report).

## Final notebook versions

- `final/AAI520_Group7_Final_Light.ipynb` calls the package and explains each result.
- `final/AAI520_Group7_Final_Full.ipynb` has the same cells, plus a "Code for this section" cell after each section that prints the real source of the functions that just ran, and an appendix with the data models and database schema.
- Both come from `scripts/build_final_notebooks.py`, so they cannot drift apart. To rebuild:
  1. `python scripts/build_final_notebooks.py build`, then `ruff format notebooks/final`
  2. Run the full notebook (`jupyter nbconvert --to notebook --execute --inplace notebooks/final/AAI520_Group7_Final_Full.ipynb`)
  3. Write section 8 (conclusions) from the results; it depends on the run, so the script leaves a placeholder
  4. `python scripts/build_final_notebooks.py light-from-full`, so the light version keeps the same outputs

## Export path for the final deliverable

The path that worked in the course repo:

1. `jupyter nbconvert --to html notebooks/final/<name>.ipynb`
2. Before printing, add this rule just before `</head>` in the HTML, or long code lines get cut off at the
   right edge of the PDF (Chrome does not wrap code cells on its own):
   `<style>pre, .highlight pre, .jp-RenderedText pre { white-space: pre-wrap !important; overflow-wrap: anywhere !important; }</style>`
3. Print the HTML to PDF with headless Chrome:
   `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer --print-to-pdf=<name>.pdf <name>.html`

For a text-only change (a disclosure, a typo), edit the Full notebook, run `light-from-full`, and export. Do not
run `build` or re-run the notebook: `build` writes notebooks with no outputs, and a re-run replaces the saved
results that section 8 describes.

HTML alone is acceptable if the PDF renders badly.
