# BPIC-17 Process Mining

Code for Assignment I of Business Process Prediction, Simulation and Optimization (TUM, WS 2026/27).

## How to run

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

Graphviz needs to be installed as well. The event log is not in the repo. Download it from https://doi.org/10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b and put `BPI Challenge 2017.csv` into a folder called `data`. Then run the notebooks in order with `jupyter lab`.

## Files

- `notebooks/01_exploration.ipynb`: basic analysis and figures
- `notebooks/02_discovery.ipynb`: Inductive Miner, conformance checking, BPMN export
- `notebooks/03_decision_mining.ipynb`: decision tree for the main decision point
- `src/bpmn_layout.py`: turns the process tree into a BPMN file for bpmn.io
- `results/`: final BPMN model and model comparison
- `figures/`: plots used in the report

The alignments in notebook 02 take around 15 to 20 minutes.
