# AI prompts and usage

## Tools and model

- AI tool: Copilot SDK in VS Code.
- Other tools used: local workspace file and shell tools, the integrated browser for local UI checks, and local Git commands. No external model API was used.

## User prompts, verbatim and in order

The original implementation request and subsequent exact messages retained in this conversation are transcribed below. Some earlier conversation context was summarized by the chat system; this file is not a complete raw platform-export of any messages omitted from that summary. I have not invented missing prompt text.
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

### 6. Assignment completion question

```
okay is the assignment complete
```

### 7. Implementation status question

```
not submission, but is the implementation done
```

### 8. README editing request

```
edit the readme such that- it seems like i have edited it for the submission
```

### 9. Local startup question

```
okay how do i start this app ?
```

### 10. Testing question

```
how do i test this
```

### 11. Assignment requirements and completion question

```
what does the take home assignment expect, i need to submit this today. is this completed?
```

### 12. Remaining-work request

```
okay what is still remaining? lets complete it one by one
```

### 13. Controller configuration selection

```
control
```

### 14. Initial controller values

```
do_target_percent=72, dwell_minutes=50
```

### 15. Controller-setting clarification

```
wait what is minimum dwell and target idk what that is so i cant choose it
```

### 16. Request for decision support

```
no i want to do that first but help me make the decision
```

### 17. Local-demo setting selection

```
demo_config
```

### 18. Demo preparation selection

```
demo
```

### 19. Final technical audit request

````text
# Boston Bioprocess — Final Technical Audit & Quality Assurance
Act as a senior full-stack engineer, ML engineer, software architect, and QA reviewer.

I have already built my Boston Bioprocess take-home assignment application, including the scheduler. Your task is to thoroughly audit the existing implementation against the original assignment, identify missing requirements, fix genuine issues, and ensure the application is technically sound.

**Do not rebuild the application or add unnecessary features. Preserve existing functionality and prioritize correctness, reliability, and engineering quality.**

## 1. Scheduler Audit
Verify that:

- The Gantt chart displays actual backend schedule data accurately.
- Scheduling violations are detected dynamically, not hardcoded.
- The operation-editing modal updates backend data and resolves violations correctly.
- Changes persist after refreshing the application.
- Invalid dates, durations, dependencies, and equipment conflicts are handled according to the assignment.
- Appropriate input validation and error handling exist.
Test valid edits, invalid edits, scheduling conflicts, and violation resolution.

## 2. ML & Closed-Loop Control Audit
Verify that:

- The supplied fermentation datasets are correctly processed, with appropriate validation and units.
- Training, validation, and testing use a defensible split without data leakage.
- The model's prediction target, forecast horizon, and evaluation metrics are documented.
- Model performance is compared against a persistence baseline using actual results.
- The closed-loop simulation correctly implements: **sensor readings → prediction → controller command → simulated device response**.
- Control commands respect all configured constraints in `limits.json`.
- Observations, predictions, proposed actions, and applied actions are clearly distinguishable.
- The simulation does not falsely imply real-world equipment validation.
Test control boundaries, invalid inputs, simulation state transitions, and prediction behavior.

## 3. Backend, Frontend & Integration Audit
Check that:

- Frontend and backend communicate through real APIs.
- Database operations and persistence work correctly.
- API errors, invalid inputs, loading states, and empty states are handled.
- The application starts reliably using documented instructions.
- No secrets, virtual environments, generated dependencies, or unnecessary files are committed.
- There are no obvious integration failures, broken routes, or misleading hardcoded outputs.
Run existing tests, add targeted tests where important coverage is missing, and verify fixes do not introduce regressions.

## 4. Documentation & Submission Audit
Review the original assignment, `README.md`, and `PROMPTS.md`.

Ensure the README accurately documents:

- Architecture and setup instructions.
- Scheduling functionality and seeded violations, if required.
- ML evaluation methodology, dataset split, metrics, and baseline comparison.
- Engineering decisions and trade-offs.
- Known limitations.
- Deployment, retraining, and monitoring considerations.
Ensure `PROMPTS.md` contains the actual AI prompts required by the assignment. Never fabricate prompt history.

Verify repository structure, submission requirements, and configuration consistency.

## 5. Engineering Quality Review
Evaluate whether the application demonstrates:

- Correct scheduling and dependency logic.
- Backend-enforced validation rather than frontend-only checks.
- Clear separation between business logic, APIs, persistence, and ML components.
- Reproducible model training and evaluation.
- Appropriate handling of edge cases and failures.
- Sensible architectural decisions without unnecessary complexity.
- Honest reporting of model limitations and simulation assumptions.
Prioritize actual correctness problems over cosmetic improvements.

## 6. Mandatory Guardrails

- **Inspect before modifying.** Do not assume files or features exist.
- Do not delete existing code, reset databases, overwrite valuable data, or perform destructive operations without approval.
- Do not force-push, rewrite Git history, change repository visibility, deploy services, or incur costs without permission.
- Do not introduce unnecessary dependencies or redesign working components.
- Do not invent requirements, scientific assumptions, evaluation results, or test outcomes.
- If a requirement is ambiguous, data are inconsistent, tests fail unexpectedly, or a fix risks breaking existing behavior, **stop and ask for human intervention**.
- When asking, explain the problem, evidence, impact, available options, and your recommended solution.
- Never conceal failures or mark unverified functionality as working.

## 7. Execution & Final Report
Follow this sequence:

1. Inspect the original assignment, repository, source code, datasets, tests, and documentation.
2. Compare the implementation against every explicit assignment requirement.
3. Identify missing functionality, bugs, risks, and weak engineering decisions.
4. Categorize findings as **Critical**, **Important**, or **Optional**.
5. Implement safe, targeted fixes for clearly understood issues. Request approval before risky or consequential changes.
6. Run relevant automated tests and end-to-end checks.
7. Verify that fixes did not break existing functionality.
When finished, provide:

- Requirements compliance checklist.
- Issues identified and fixes completed.
- Files modified and why.
- Tests executed, with actual results.
- Remaining bugs, limitations, and unverified areas.
- Any decisions requiring my intervention.
- Final technical readiness assessment.
**Important: Do not generate a demo script, video narration, recording plan, or presentation material. That will be handled separately.**

Your objective is to ensure the application is complete, reliable, reproducible, and aligned with the original assignment — not simply to make it look finished.
````

### 20. Replay isolation migration approval

```
additive_migration
```

### 21. Optional extensions E2 and E3

````text
implement e2 fully and also implement- E3. Drag to reschedule
On the Gantt grid, drag a unit operation to another day or another equipment lane. Save through your
update endpoint and show the returned violations inline without a page reload. Describe how you keep
the grid and the violation list consistent while a drag is in progress.
````

## Changes made and issues caught

- The scheduling backend saves operations and returns current rule violations; this was chosen after the user approved that behavior.
- The first simulator implementation held the initial feed value instead of replaying the supplied feed trace before a command. A focused test caught the mismatch; the simulator now follows the source run until a command is applied.
- The first manual-command UI calculation could use a stale process time during accelerated replay. A browser check reproduced the failure; the UI now submits a relative delay and the backend anchors it to process time when received. A browser run showed the command move from pending to applied.
- The controller was configured with 50% DO and a 10-process-minute dwell only after the user selected them as illustrative local-demo values. They are not scientifically validated process guidance and are not code defaults.
- A final audit reproduced stale data when restarting a source run at an earlier process minute. After user approval, the implementation added replay-instance identifiers and a non-destructive additive database migration to isolate new replay readings, predictions and commands without deleting historical rows.
- E2 uses a fresh prediction five minutes ahead, matching the actuator lag. Missing or stale forecasts cause no action; pending commands, dwell, configured feed limits, and the existing API validation remain in force.
- E3 keeps the committed schedule and violations unchanged during the drag preview. After the update endpoint returns, the UI replaces the operation and its related violations in memory; failures discard the preview and retain the saved state.
- The application is deployed on the Render and Neon Free tiers at https://boston-bioprocess-demo.onrender.com. No paid services were selected. No recording has been created.
