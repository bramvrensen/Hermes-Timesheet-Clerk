# HERMES Timesheet Clerk — Functioneel ontwerp

## 1. Doel

Timesheet Clerk ondersteunt HERMES bij het voorbereiden, controleren, leren en uiteindelijk boeken van uren uit Clockify naar Simplicate.

Het product is human-in-the-loop: HERMES interpreteert en stelt mappings voor, Python bewaakt alle structurele state, en de frontend blijft de plek voor review, correctie en approval.

## 2. Ontwerpprincipes

1. **HERMES beslist mappings, niet state.** HERMES kiest mapping, autonomy tier en rationale voor expliciet aangeleverde work items.
2. **Python bezit het booking plan.** Plan-ID, week, Clockify source facts, durations, coverage, revisions, mergegedrag en persistence worden deterministisch door de plugin beheerd.
3. **De frontend controleert.** Streamlit toont het plan, laat corrigeren en accorderen, registreert feedback en voert uitsluitend goedgekeurde boekingen uit.
4. **Clockify is source truth.** Description, client, project, tags, start/end en originele duur worden live door de plugin gelezen en niet door een LLM gereconstrueerd.
5. **Integratiecode is saai.** Clockify- en Simplicate-clients verbergen authenticatie, pagination, retries, foutafhandeling, ID-formattering en timezone-quirks.
6. **De SKILL bevat mappingpolicy.** AUTO/PROPOSE/ASK, evidence, confidence en learning policy blijven buiten structurele persistence-logica.
7. **Feedback is bewijs, geen directe wet.** Correcties worden append-only vastgelegd en kunnen later tot rules promoveren.
8. **Assignment-first, maar planning en beschikbaarheid zijn verschillend.** Een daadwerkelijk geplande assignment is sterker bewijs dan een slechts beschikbare booking candidate.
9. **Writes zijn deterministisch.** Een approved snapshot wordt exact uitgevoerd; bookingcode mag niet stil remappen.
10. **Rebuild is nooit destructief herstel.** Een nieuwe weekstate wordt eerst volledig gebouwd en gevalideerd; pas daarna mag de active pointer wisselen.
11. **Rebuild vereist expliciete gebruikerintentie.** Een refresh mag nooit autonoom escaleren naar rebuild.
12. **Eén product, één repository, één versie.** Plugin, runtime contract, frontend, core en documentatie worden samen ontwikkeld.

## 3. Architectuur

```text
Clockify REST + bestaande Clerk state
                  │
                  ▼
      timesheet_mapping_prepare
                  │
                  ▼
          exacte work_items
                  │
                  ▼
        HERMES Timesheet Agent
        ├─ Timesheet SKILL
        ├─ learned rules
        ├─ precedents
        └─ feedback history
                  │
          mapping decisions only
                  │
                  ▼
       timesheet_mapping_apply
                  │
                  ▼
      deterministic Python core
      ├─ live Clockify re-fetch
      ├─ source reconciliation
      ├─ merge/rebuild
      ├─ coverage validation
      ├─ schema validation
      └─ revision persistence
                  │
                  ▼
             booking plan
                  │
                  ▼
          Streamlit frontend
       review / correct / approve
           │                │
           ▼                ▼
      feedback events   approved snapshot
                              │
                              ▼
                    deterministic booking
                              │
                              ▼
                          Simplicate
```

Het booking plan is een persisted contract tussen core en frontend, maar niet langer een payload die HERMES zelf construeert.

## 4. Verantwoordelijkheden

### 4.1 HERMES Timesheet Agent

HERMES:

- ontvangt alleen de work items waarvoor een mappingbeslissing nodig is;
- leest runtime config, learning context en benodigde Simplicate-context;
- kiest per work item `assignment` of `direct` mapping;
- bepaalt `AUTO`, `PROPOSE` of `ASK`;
- geeft rationale, confidence en mapping-source evidence terug;
- verzint geen IDs;
- verandert geen Clerk filesystem/state buiten de Clerk tools;
- boekt nooit tijdens generation, refresh of rebuild.

HERMES maakt geen volledig planobject, bepaalt geen revisionnummer en kopieert geen Clockify source facts naar state.

### 4.2 Deterministische Python core

De core:

- leest live Clockify source rows;
- vergelijkt live source truth met stored source snapshots én daadwerkelijke plan coverage;
- bepaalt CREATE, REFRESH of REBUILD;
- maakt de exacte mapping-worklist;
- valideert dat precies de vereiste mapping decisions worden teruggegeven;
- bouwt canonical plan entries;
- bewaart human-reviewed mappings tijdens incremental refresh;
- reconcilieert verwijderde Clockify sources;
- valideert volledige live Clockify coverage;
- valideert het plancontract;
- persist één nieuwe working revision;
- beheert de active pointer.

### 4.3 Streamlit frontend

Streamlit:

- opent een specifieke working planrevision;
- toont week-, dag- en entry-status;
- laat mapping, duur, planning en ignore-status corrigeren;
- registreert materiële correcties als feedback-events;
- laat PROPOSE/ASK bevestigen;
- maakt immutable approval snapshots;
- toont planner job status;
- kan expliciet een safe rebuild starten;
- blijft Configuration, SKILL en State tonen wanneer geen actief plan beschikbaar is.

Streamlit runt geen mappingintelligentie.

### 4.4 Integratielaag

De integratielaag bevat transport- en normalisatielogica voor Clockify en Simplicate. Secrets komen niet in plans, feedback, rules of logs terecht.

## 5. Planner workflow

### 5.1 Create / normal refresh

```text
timesheet_mapping_prepare(rebuild=false)
        │
        ├─ no_op=true → deterministic summary → stop
        │
        └─ work_items
              │
              ▼
       HERMES mapping decisions
              │
              ▼
timesheet_mapping_apply(rebuild=false)
              │
              ▼
      one validated revision
```

De rebuild flag is immutable voor de run. Een failure in een `rebuild=false` run mag nooit leiden tot een autonome retry met `rebuild=true`.

### 5.2 Safe rebuild

Een rebuild bestaat alleen na expliciete gebruikerintentie.

```text
timesheet_mapping_prepare(rebuild=true)
              │
        alle live sources
              │
              ▼
       HERMES decisions
              │
              ▼
timesheet_mapping_apply(rebuild=true)
              │
              ▼
   complete replacement candidate
              │
     coverage + schema valid?
          │           │
         nee          ja
          │           │
   oude state blijft  persist replacement
                      │
                      ▼
                 active switch
```

Het oude working plan wordt niet vooraf verwijderd.

## 6. Clockify source integrity

Clockify source truth bevat minimaal:

- source ID;
- description;
- client;
- project;
- tags;
- start;
- end;
- original duration.

Bij apply wordt Clockify opnieuw live gelezen. Daardoor kan een oude LLM-response geen stale titel, duur of timestamp terugschrijven.

### 6.1 Changed source

Een gewijzigde live source wordt opnieuw als work item aangeboden. Python schrijft de nieuwe canonical source facts weg. Een eerder human-reviewed booking target blijft behouden tenzij de reviewstate dat niet toestaat.

### 6.2 Removed source

Removed detection is gebaseerd op:

```text
plan covered source IDs - live Clockify source IDs
```

Snapshot history is aanvullende evidence, maar niet de enige bron.

Gedrag:

- single-source row verdwenen → deterministisch verwijderen;
- legacy aggregate waarvan alle sources verdwenen → deterministisch verwijderen;
- legacy aggregate waarvan slechts enkele sources verdwenen → `requires_explicit_rebuild`;
- `requires_explicit_rebuild` stopt de run; HERMES mag niet autonoom rebuilden.

## 7. Simplicate assignment-model

### 7.1 Geplande assignment

Een geplande assignment:

- hoort bij de geconfigureerde medewerker;
- is niet blocked/done;
- heeft geldige start- en einddatum;
- overlapt de relevante entrydatum/periode.

Dit is primaire planning evidence.

### 7.2 Booking candidate

Een booking candidate:

- hoort bij de medewerker;
- is geldig en niet blocked/done;
- is gekoppeld aan een actief project en geschikte service;
- mag undated zijn.

Een undated candidate is een mogelijk booking target, maar geen bewijs dat de gebruiker op die dag gepland stond.

### 7.3 Mappingvolgorde

```text
Clockify work item
    ↓
geplande assignments
    ↓
betrouwbare match?
    ├─ ja → assignment mode
    └─ nee
         ↓
andere evidence + booking candidates
         ↓
voldoende onderbouwd?
    ├─ ja → assignment mode volgens tier policy
    └─ nee → direct mapping
```

## 8. Mapping decision contract

Per work item levert HERMES precies één decision:

```json
{
  "source_id": "clockify-id",
  "tier": "AUTO",
  "booking_mode": "direct",
  "direct_mapping": {
    "project_id": "...",
    "service_id": "...",
    "hour_type_id": "..."
  },
  "ignored": false,
  "why": "mapping evidence",
  "why_not_auto": "",
  "confidence": 0.98
}
```

AUTO vereist een compleet geldig target. PROPOSE/ASK mogen unresolved blijven volgens het plancontract.

## 9. Review en learning

Feedback lifecycle:

```text
feedback event → precedent → candidate rule → confirmed rule
       ▲                                      │
       └──────── success/correction feedback ─┘
```

Een gecorrigeerde AUTO is sterk negatief bewijs. Semantische similarity alleen levert geen AUTO op tenzij runtime policy dat expliciet toestaat.

Human review is tijdens incremental refresh sterker dan een nieuwe agent proposal voor booking fields.

## 10. Plan lifecycle

```text
DRAFT → IN_REVIEW → APPROVED → BOOKING → BOOKED
                  ↘ SUPERSEDED / FAILED
```

Working revisions zijn mutable via nieuwe immutable revisionfiles. Approved snapshots, receipts en feedback zijn aparte durable artifacts.

Minimale planmetadata:

```json
{
  "schema_version": 1,
  "plan_id": "plan-2026-08-24-r-...",
  "revision": 1,
  "status": "DRAFT",
  "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
  "contract_hours_default": 36.0,
  "target_hours": 36.0,
  "entries": []
}
```

## 11. Approval, booking en idempotency

Booking vindt alleen plaats vanuit een immutable approved snapshot.

Bij toekomstige live booking:

1. validate review readiness;
2. create/read immutable approval snapshot;
3. build exact Simplicate payloads;
4. preflight existing booked hours/receipts;
5. execute only non-duplicate rows;
6. persist per-entry receipt;
7. never blindly replay an entire partial-failure batch.

Live Simplicate writes blijven uitgeschakeld totdat deze flow gecontroleerd gevalideerd is.

## 12. Background planner lifecycle

Frontend planner runs gebruiken een supervised runner.

```text
STARTING → RUNNING → SUCCEEDED
                   ↘ FAILED
```

Een verdwenen runner wordt `FAILED`; stoppen van een proces is niet hetzelfde als succesvolle plangeneratie.

## 13. State en recovery

Default production state:

```text
/home/hermes/.hermes/timesheet-clerk
```

Belangrijke artifacts:

```text
config.json
SKILL.md
active_plan.json
plans/
approvals/
receipts/
feedback_events.jsonl
rules.json
logs/
planner-sync-status.json
```

Als `active_plan.json` ontbreekt terwijl stored plans bestaan, mag de pointer deterministisch naar het nieuwste stored plan worden hersteld.

## 14. Deployment en versiebeheer

Canonical repository:

```text
bramvrensen/Hermes-Timesheet-Clerk
```

Plugin, frontend, SKILL contract, docs en tests delen één productversie. CI compileert en test iedere push naar `main`.

## 15. Acceptatiecriteria

De plannerarchitectuur is geslaagd wanneer:

- HERMES geen volledig plan kan fabriceren;
- Clockify source facts uitsluitend uit live integration data komen;
- gewijzigde sources betrouwbaar worden bijgewerkt;
- verwijderde sources veilig worden gereconcilieerd;
- ambiguity bij legacy aggregates fail-closed is;
- refresh nooit autonoom naar rebuild escaleert;
- failed rebuild bestaande state intact laat;
- human-reviewed mappings incremental behouden blijven;
- frontend state ook zonder active pointer herstelbaar is;
- background job status een echte terminal success/failure state heeft;
- approvals en toekomstige bookings deterministisch en idempotent blijven.
