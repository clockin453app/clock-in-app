# TimIQ Migration Tracker

## Rule

Every refactor step must be small, reversible, and tested before continuing.

## Current safe state

- Existing routes remain unchanged.
- Existing templates remain unchanged.
- New shell/theme files are added first but not wired until the next approved step.

## Step records

| Step | Status | Files changed | Test result | Notes |
|---|---|---|---|---|
| 0 | Pending | none | pending | Confirm current app runs before adding files |
| 1 | Pending | add shell/theme files only | pending | No app behavior should change |
| 2 | Pending | wire shell safely | pending | Requires explicit approval |
| 3 | Pending | migrate Time Records page | pending | First page migration |
