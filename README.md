# HERMES Timesheet Clerk

Human-in-the-loop timesheet planning and booking for HERMES Agent.

The Timesheet Clerk prepares a weekly booking plan from Clockify and Simplicate context, lets the user review and correct that plan in a Streamlit UI, learns from those corrections, and books only the approved result to Simplicate.

> **Status:** design complete, implementation starting. The functional design in [`docs/DESIGN.md`](docs/DESIGN.md) is the source of truth.

## Core principles

- **HERMES thinks.** The Timesheet Agent gathers context, maps time entries, uses learned rules and produces the booking plan.
- **Streamlit reviews.** The UI presents the plan, supports overrides and approval, records feedback and executes only approved bookings.
- **`booking_plan.json` is the contract.** Agent and UI exchange explicit, versioned state rather than hidden shared business logic.
- **Tools are boring.** Clockify and Simplicate API clients hide authentication, pagination, retries, ID quirks, timezone handling and response normalization.
- **The SKILL owns policy.** Autonomy thresholds, confidence interpretation, generalisation and learning policy live in the HERMES skill, not as hard-coded Python business constants.
- **Assignment first.** A Clockify entry is first matched to a valid Simplicate assignment. Direct customer → project → task → hour-type mapping is the fallback.
- **Writes are deterministic.** An approved plan is executed exactly as approved. Integration tools do not silently remap it.

## Intended architecture

```text
Clockify + Simplicate + other permitted context
                    │
                    ▼
          HERMES Timesheet Agent
             SKILL + learned rules
                    │
                    ▼
            booking_plan.json
                    │
                    ▼
              Streamlit UI
          review / correct / approve
              │             │
              ▼             ▼
       feedback events   approved plan
                            │
                            ▼
                    Simplicate booking
```

The project is intended to be shipped as one HERMES Timesheet Clerk codebase containing the HERMES integration, SKILL, shared API clients and Streamlit frontend. The frontend may run as its own process, but it is versioned and deployed together with the Clerk.

## Integrations

The Clerk talks directly to the REST APIs. MCP is not part of the Clockify/Simplicate data path.

### Clockify

Typical capabilities:

- time entries for a period;
- projects;
- clients;
- supporting metadata required by the Timesheet Agent.

Clockify-specific authentication, pagination and response details stay inside the integration layer.

### Simplicate

Typical capabilities:

- projects;
- tasks/services;
- hour types;
- employee assignments/planning;
- existing booked hours;
- assignment-based booking;
- direct booking when no assignment applies.

Simplicate-specific ID prefixes, legacy/UUID service IDs, query parameter quirks, time/date corrections and booking payload details must never leak into the SKILL or learned memory.

Assignment booking is exposed to the application as a separate domain capability from direct booking. The exact Simplicate REST method/payload must be validated against the existing tested implementation and the live API before that write capability is finalised.

## Review UI

The frontend is intended to live at:

```text
https://<hermes-host>/timesheet
```

It has its own authentication and is reverse-proxied by Caddy. The normal contractual week defaults to **36 hours**, while each week has an editable `target_hours` value for short weeks, leave and holidays.

Manual direct mapping uses cascading selections:

```text
Customer → Project → Task → Hour type
```

When an assignment is selected, the assignment itself is the booking target. Customer, project, task and hour type are then shown read-only. Assignment choices are labelled with enough context to disambiguate similar names, at minimum:

```text
Customer · Project · Assignment
```

## Learning and autonomy

The learning loop is evidence based rather than counter based:

```text
feedback event
    ↓
precedent
    ↓
candidate rule
    ↓
confirmed rule
    ↓
autonomous application
    ↓
success / correction
    ↺
```

Confidence can be used as a signal, but Python code does not contain business thresholds such as `confidence >= 0.70` or `seen twice = AUTO`. Those policies belong in the SKILL.

## Repository direction

The implementation is expected to evolve roughly along these boundaries:

```text
Hermes-Timesheet-Clerk/
├── README.md
├── docs/
│   └── DESIGN.md
├── plugin / HERMES integration
├── skill / SKILL.md
├── shared integration clients
├── Streamlit frontend
└── tests
```

The exact package layout may change during implementation, but the responsibility boundaries in the design should not change without updating the design first.

## Documentation policy

`docs/DESIGN.md` is the canonical functional and architectural specification.

When implementation work changes behaviour, data contracts, autonomy policy, integration responsibilities, deployment, UI behaviour or the booking flow, **the documentation must be updated in the same change**. The repository must not rely on chat history or an agent context window to explain how the Clerk is supposed to work.

In practice:

1. design decisions are written to `docs/DESIGN.md` before or together with implementation;
2. README stays a concise overview and installation/usage entry point;
3. API quirks belong in code comments/tests and integration documentation, not in the SKILL;
4. behaviour that exists only in conversation history is considered undocumented and therefore not part of the implementation contract.

## Design

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full current specification.
