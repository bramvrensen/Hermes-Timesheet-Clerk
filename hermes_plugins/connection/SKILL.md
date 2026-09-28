---
name: timesheet-clerk
description: Prepare timesheets and check their status through the independent Timesheet Clerk application.
---

# Timesheet Clerk

Timesheet Clerk is a separate application that owns its own state and planner.
Use timesheet_clerk_generate for the exact Monday and Sunday requested by the user.
This starts a background job; use timesheet_clerk_job to check the returned job ID.
Never report success until the job is SUCCEEDED; show an actionable failure if it is FAILED.
Use timesheet_clerk_status for progress, the current plan summary and the review URL.
The user reviews and books real hours in the Timesheet Clerk webinterface.
This connection cannot book hours, rebuild plans, read credentials, edit state or configure the server.
Never try to reach Timesheet Clerk through terminal commands or guessed files.
