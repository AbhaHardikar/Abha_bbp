# AI prompts and usage

## Tools and model

- AI tool: Copilot SDK in VS Code.
- Model identifier: not exposed in this session’s metadata; it is intentionally not guessed.
- Other tools used: local workspace file and shell tools, the integrated browser for local UI checks, and GitHub read-only metadata lookup for repository/branch inspection. No external model API was used.

## Prompts, verbatim and in order

### 1. Initial task

````text
# Boston Bioprocess Assignment — AI Coding Agent Instructions
You are my senior full-stack and ML engineer. Help me complete the Boston Bioprocess Full-Stack Software Engineer take-home assignment. Prioritize correctness, simplicity, maintainability, and a working end-to-end application over unnecessary features.

## 1. Current project state
I am working on a Mac using VS Code.

Project root: `~/Boston_Bioprocess`

GitHub repository: `https://github.com/AbhaHardikar/Abha_bbp.git`

Current structure:

```
Boston_Bioprocess/
├── .gitignore
├── backend/
│   ├── .venv/
│   └── main.py
├── frontend/
└── data_kit/
    ├── run_A.csv
    ├── run_B.csv
    ├── run_C.csv
    ├── limits.json
    └── README
```
The structure above is the intended layout; inspect the actual files before assuming they exist.

The backend uses Python 3.12, FastAPI, Uvicorn, SQLModel, pandas, scikit-learn, and joblib. The existing FastAPI application has working `/` and `/health` endpoints. The virtual environment and dependencies are already set up.

Git is configured and the remote is added. Verify the current commit and working-tree state before making changes.

## 2. What we need to build
Read the original assignment and supplied data documentation first. Implement every required feature, including:

- **Scheduling backend:** Required data models, APIs, validation, persistence, and scheduling constraints.
- **Gantt frontend:** A usable interface that retrieves actual schedule data from the backend and displays operations correctly.
- **ML pipeline:** Process the supplied fermentation datasets, train and evaluate an appropriate model, and report honest results.
- **Closed-loop simulation:** Implement the required simulated bioreactor control workflow, respecting the limits in `limits.json`.
- **Submission:** Complete README.md and PROMPTS.md, test the application, and prepare the required hosted link and demonstration video if specified.
Use the original assignment as the source of truth. Do not invent missing requirements or unnecessary complexity.

## 3. How to work
Work in small, independently verifiable milestones:

1. Inspect the repository, assignment, datasets, dependencies, and Git state.
2. Propose the architecture and implementation plan.
3. Build the backend and test it.
4. Build and integrate the frontend and Gantt chart.
5. Implement and evaluate the ML model.
6. Implement and test the simulated control workflow.
7. Run end-to-end tests and prepare submission documentation.
Preserve existing working code. Use the simplest suitable architecture, meaningful error handling, input validation, and automated tests. Keep the frontend connected to real backend APIs rather than hardcoded demo data.

For ML, prevent data leakage and use separate runs for training, validation, and final testing where appropriate. Compare against a suitable baseline and never fabricate performance metrics.

For simulation, enforce all configured constraints and clearly distinguish observations, predictions, proposed actions, and applied actions.

## 4. Mandatory safety guardrails

- **Inspect before editing.** Never assume files, features, or commits exist without checking.
- Never delete, overwrite, reset, or rewrite existing work without my approval.
- Never force-push, change repository visibility, publish data, or incur cloud costs without my approval.
- Never commit secrets, `.env` files, virtual environments, or generated dependencies.
- If requirements are ambiguous, data are inconsistent, a test fails unexpectedly, or a safe fix is uncertain, stop and ask me.
- When requesting intervention, explain the problem, evidence, impact, available options, and your recommendation.
- Do not claim success unless you have verified it. Report untested functionality and known limitations honestly.

## 5. Completion criteria
The assignment is complete only when all required features work together, scheduling and visualization are correct, the ML evaluation is reproducible, simulated control respects constraints, tests have been run, and documentation and submission requirements are addressed.

At the end of each milestone, summarize what changed, which files were affected, what tests were run and their results, known issues, and the next step.

## First task
**Perform an audit only. Do not modify any files yet.** Inspect the current repository and original assignment, then give me the findings, a proposed architecture, an implementation plan, and any questions requiring my decision. Wait for my approval before making major changes.
````

### 2. Assignment brief location

```
its here /Users/abha/Boston_Bioprocess/data_kit/Take_Home_SWE_ML_Brief.pdf
```

### 3. Cost and deferral clarification

```
do not ever do anything that costs me,
and defer
```

### 4. Control, save, and hosting decisions

```
decisions:
we will work on the control targets later
yes go with saving violations
i want to go for a free choice was hosting
```

### 5. Implementation approval

```
yes
```

## Changes made and issues caught

- The scheduling backend saves operations and returns current rule violations; this was chosen after the user approved that behavior.
- The first simulator implementation held the initial feed value instead of replaying the supplied feed trace before a command. A focused test caught the mismatch; the simulator now follows the source run until a command is applied.
- The first manual-command UI calculation could use a stale polled process time during accelerated replay. A browser check reproduced a rejected command; the UI now fetches the current control state immediately before calculating the apply time. A local browser test then observed the command progress from pending to applied and the feed trace update.
- No target or dwell default was selected. Automatic control remains unconfigured until the user supplies those settings.
- The browser check used an in-memory database. No deployment, paid service, hosted link, or recording has been created.
