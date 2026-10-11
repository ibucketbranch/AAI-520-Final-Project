# Notebooks

**Overview:** logic lives in `src/`, notebooks import it. Install the package first (`make setup`, or `pip install -e .` in Colab).

## Rules

- Dev notebooks go under `notebooks/dev/`, named `<initials>_<topic>.ipynb` (for example `mv_planner_probe.ipynb`).
- Outputs are stripped on commit by nbstripout; CI fails any dev notebook that still carries outputs. Dev notebooks are never merged into each other.
- The single final notebook under `notebooks/final/` is assembled in the last week from the package and is the only notebook that keeps outputs (Kahila, Sep 11: one combined notebook; HTML is acceptable; comments stay in the notebook even with a report).

## Final notebook versions

- `dev/gp_final_notebook_light.ipynb` is the short working version. It mainly calls package functions and keeps no saved output.
- `final/AAI520_AI_Investment_Committee.ipynb` is the submission version. It follows the same demo but also includes the important source code and saved offline output so the grader can review it without opening other files.
- `scripts/build_course_notebooks.py` builds both versions from the same text and code cells so they do not drift apart.

## Export path for the final deliverable

The path that worked in the course repo:

1. `jupyter nbconvert --to html notebooks/final/<name>.ipynb`
2. Print the HTML to PDF with headless Chrome:
   `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --print-to-pdf=<name>.pdf <name>.html`

HTML alone is acceptable if the PDF renders badly.
