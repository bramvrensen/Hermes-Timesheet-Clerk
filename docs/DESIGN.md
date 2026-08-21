# HERMES Timesheet Clerk — Definitief Functioneel Ontwerp

## 1. Doel en ontwerpprincipes

De Timesheet Clerk ondersteunt HERMES bij het voorbereiden, controleren, leren en boeken van uren uit Clockify naar Simplicate.

Kernprincipes:

1. **HERMES denkt.** De Timesheet Agent verzamelt context, interpreteert Clockify entries, kiest mappings, plant tijdvakken en bepaalt autonomie.
2. **De frontend controleert.** De Streamlit UI toont het plan, laat corrigeren en accorderen, registreert feedback en voert uitsluitend goedgekeurde boekingen uit.
3. **`booking_plan.json` is het contract.** Agent en UI communiceren via expliciete, versioned state.
4. **Integratiecode is saai.** Clockify- en Simplicate-clients verbergen authenticatie, pagination, retries, foutafhandeling, ID-formattering, timezone- en andere API-quirks.
5. **De SKILL bevat policy.** Autonomievoorwaarden, confidence-interpretatie, generalisatie en learning policy worden niet als businessdrempels in Python hardcoded.
6. **Feedback is bewijs, geen directe wet.** Correcties worden append-only vastgelegd en kunnen door HERMES worden ontwikkeld van precedent naar candidate/confirmed rule.
7. **Assignment-first, maar planning en beschikbaarheid zijn verschillend.** Een daadwerkelijk geplande assignment is sterk bewijs. Een undated assignment kan een geldig booking target zijn maar bewijst niet dat de gebruiker daarop vandaag gepland staat.
8. **Writes zijn deterministisch.** Een approved snapshot wordt exact uitgevoerd; tools mogen niet stilletjes remappen.
9. **Eén product, één repository, één versie.** Plugin, SKILL, gedeelde integratiecode en Streamlit frontend worden samen ontwikkeld en gedeployed. Ze hoeven operationeel niet onafhankelijk van HERMES te blijven draaien.

## 2. Productarchitectuur

```text
Clockify REST + Simplicate REST + aanvullende toegestane context
                              │
                              ▼
                     HERMES Timesheet Agent
                    ├─ Timesheet SKILL
                    ├─ learned rules
                    ├─ precedents
                    └─ feedback history
                              │
                              ▼
                     booking_plan.json
                              │
                              ▼
                      Streamlit frontend
                   review / correct / approve
                    │                    │
                    ▼                    ▼
             feedback events       approved snapshot
                                         │
                                         ▼
                                 deterministic booking
                                         │
                                         ▼
                                     Simplicate
```

De codebase wordt als één HERMES Timesheet Clerk GitHub-repository beheerd en via de HERMES plugin-install/updateflow gedeployed. Streamlit kan technisch als apart proces draaien, maar is onderdeel van dezelfde productversie en lifecycle.

## 3. Verantwoordelijkheden

### 3.1 HERMES Timesheet Agent

De agent:

- leest Clockify via de Timesheet Clerk tools;
- leest Simplicate masterdata, geplande assignments, beschikbare assignment-kandidaten en bestaande boekingen via tools;
- haalt aanvullende context op zoals toegestaan door de SKILL;
- leest confirmed rules, precedenten en feedback;
- consolideert Clockify entries alleen binnen dezelfde kalenderdag;
- maakt de sequentiële dagplanning;
- probeert per entry eerst een **geplande assignment** te matchen;
- gebruikt beschikbare maar niet geplande assignments alleen als zwakkere fallback/override-evidence;
- valt terug op directe klant → project → taak → uurcode-mapping wanneer geen geschikte assignment hoort te worden gebruikt;
- bepaalt autonomy tier en mapping source;
- schrijft atomair een nieuw `booking_plan.json`.

De agent boekt niet tijdens plan generation.

### 3.2 Streamlit frontend

Streamlit:

- leest één specifieke planversie;
- toont week-, dag- en entry-status;
- toont AUTO compact maar altijd corrigeerbaar;
- laat duur, planning en mappings corrigeren;
- registreert materiële correcties als feedback-events;
- laat PROPOSE/ASK bevestigen;
- maakt een immutable approval snapshot;
- boekt alleen uit dit snapshot;
- registreert per booking het resultaat.

Streamlit:

- runt geen LLM;
- bepaalt geen autonomie;
- leert geen rules af;
- implementeert geen Clockify/Simplicate transportquirks.

### 3.3 Integratielaag

De integratielaag bevat uitsluitend transport- en normalisatielogica.

Huidige read-capabilities voor HERMES:

- `timesheet_clockify_entries`
- `timesheet_simplicate_context`
- `timesheet_simplicate_assignments`
- `timesheet_simplicate_available_assignments`
- `timesheet_simplicate_booked_hours`

Geplande write-capabilities voor de approval/backend-flow:

- `simplicate_book_on_assignment(...)`
- `simplicate_book_direct(...)`

De agent krijgt geen vrije booking capability tijdens plan generation.

## 4. Simplicate assignment-model

### 4.1 Geplande assignment

Een geplande assignment is:

- gekoppeld aan de geconfigureerde medewerker via Simplicate `employees[]`;
- niet blocked (`status.is_blocked = false`);
- voorzien van zowel `start_date` als `end_date`;
- overlappend met de gevraagde datum/periode.

Deze set wordt gebruikt als primaire planning evidence en wordt door `timesheet_simplicate_assignments` teruggegeven.

Simplicate documenteert in de Insights-laag dagelijkse `api_project_assignments_facts`. Die facts bevatten alleen assignments met start- én einddatum. De gewone REST API publiceert geen equivalente employee/day facts endpoint. Daarom gebruikt de REST-integratie de dated assignment range als planning evidence.

### 4.2 Beschikbare assignment

Een beschikbare assignment:

- is gekoppeld aan de medewerker;
- is niet blocked;
- is, indien dated, geldig voor de gevraagde periode;
- mag ook undated zijn.

Een undated assignment mag een geldig handmatig booking target of mapping-kandidaat zijn, maar geldt **niet** als bewijs dat de gebruiker op die specifieke dag gepland staat.

`timesheet_simplicate_available_assignments` levert deze kandidaten voor overrides en fallback mapping.

### 4.3 Contextcontract

`timesheet_simplicate_context` levert minimaal:

```text
projects
services
hour_types
planned_assignments
available_assignments
```

Voor backwards compatibility mag `assignments` tijdelijk aliasen naar `planned_assignments`. Nieuwe logica gebruikt de expliciete velden.

### 4.4 Assignment-first beslisvolgorde

```text
Clockify entry
    ↓
Geplande assignments voor entry-datum
    ↓
Eén betrouwbare match?
    ├─ Ja → booking_mode = assignment
    └─ Nee
         ↓
Andere evidence + beschikbare assignment-kandidaten
         ↓
Geschikte assignment voldoende onderbouwd?
    ├─ Ja → PROPOSE/ASK of AUTO volgens SKILL/evidence
    └─ Nee → booking_mode = direct
             Klant → Project → Taak → Uurcode
```

Harde regel: een undated assignment wordt nooit als `planned` gepresenteerd.

## 5. UI-regels

### 5.1 Weekuren

- `contract_hours_default` staat standaard op **36,0 uur**;
- iedere week heeft een aanpasbare `target_hours`;
- volledigheidschecks vergelijken tegen `target_hours`, niet tegen een hardcoded 36/40 uur;
- korte weken, verlof en feestdagen kunnen zo zonder configuratiewijziging worden verwerkt.

### 5.2 Assignment override

Wanneer een assignment is geselecteerd:

- toont de UI een assignment-dropdown;
- label is minimaal `Klant · Project · Assignment`;
- klant, project, taak/service en uurcode zijn read-only afgeleide informatie;
- deze onderliggende velden zijn niet afzonderlijk wijzigbaar;
- override betekent: andere assignment kiezen of expliciet overschakelen naar direct mapping.

De dropdown mag zowel geplande als beschikbare geldige override-kandidaten bevatten, maar moet planningstatus visueel/semantisch kunnen onderscheiden.

### 5.3 Directe mapping

Alleen bij `booking_mode = direct` verschijnt de cascade:

```text
Klant → Project → Taak → Uurcode
```

Elke dropdown toont uitsluitend waarden die geldig zijn binnen de keuze erboven.

## 6. Leerloop en autonomie

Kennisniveaus:

```text
feedback event → precedent → candidate rule → confirmed rule
       ▲                                      │
       └──────── success/correction feedback ─┘
```

Feedback is append-only. Rules zijn afgeleid en mogen worden gedeactiveerd of gedegradeerd.

Autonomie gebruikt `AUTO`, `PROPOSE` en `ASK` en is evidence-based. De SKILL bepaalt onder andere:

- bewijsvereisten voor AUTO;
- scope en match-specificity;
- recency;
- conflicting evidence;
- hoe correcties rules degraderen;
- rol van confidence;
- verschil in bewijskracht tussen geplande en alleen beschikbare assignments.

Semantische similarity alleen levert geen AUTO op. Een undated assignment alleen levert geen planning-evidence op.

Een gecorrigeerde AUTO is zwaar negatief bewijs.

## 7. `booking_plan.json`

Lifecycle:

```text
GENERATING → DRAFT → IN_REVIEW → APPROVED → BOOKING → BOOKED
                              ↘ SUPERSEDED / FAILED
```

Minimale metadata:

```json
{
  "schema_version": 1,
  "plan_id": "2026-W34-<uuid>",
  "revision": 1,
  "status": "DRAFT",
  "generated_at": "2026-08-21T18:00:00Z",
  "week": {"monday": "2026-08-17", "sunday": "2026-08-23"},
  "contract_hours_default": 36.0,
  "target_hours": 36.0,
  "entries": []
}
```

Een entry bevat minimaal:

- stabiele `entry_id`;
- Clockify source IDs;
- datum en source context;
- originele/geplande duur;
- planned start/end;
- `booking_mode`: `assignment` of `direct`;
- assignment ID/context en planningstatus indien relevant;
- directe mappingvelden indien relevant;
- tier/source/confidence;
- compacte `why` en `why_not_auto`;
- reconciliation state;
- review/ignore/booking state.

Simplicate transportprefixes komen niet in dit plan voor.

## 8. Approval, booking en idempotency

Bij `Boek Dag` of `Boek Week`:

1. valideert Streamlit review-readiness;
2. controleert het geopende `plan_id` + revision;
3. schrijft feedback-events;
4. maakt een immutable approved snapshot;
5. gebruikt uitsluitend dit snapshot voor writes;
6. gebruikt voor assignment-mode de assignment-booking capability;
7. gebruikt voor direct-mode de directe booking capability;
8. slaat per write response-ID/status op;
9. herhaalt bij partial failure niet blind de hele batch.

Booking receipts bevatten minimaal plan/entry/source IDs, approved target, datum/duur, Simplicate response ID en timestamp.

Reconciliatievoorkeur:

1. expliciete source/reference link indien beschikbaar;
2. lokale receipt met Simplicate ID;
3. sterke samengestelde fingerprint;
4. alleen bij uniciteit: datum + booking target + duur + note/fingerprint.

Ambigue matches worden nooit automatisch `BOOKED`.

## 9. Timeline en consolidatie

- Clockify entries worden nooit over kalenderdagen heen geconsolideerd.
- De agent maakt de initiële sequentiële dagplanning.
- Een handmatige duurwijziging in Streamlit mag deterministisch opvolgende tijdvakken van dezelfde dag verschuiven.
- Dit is reken-/presentatielogica, geen mappingintelligentie.

## 10. Fail-safe gedrag

- ontbrekende/ongeldige masterdata blokkeert booking;
- conflicting rules verlagen autonomie;
- API-fouten veranderen geen state alsof een write geslaagd is;
- partial booking behoudt per-entry status;
- approved snapshots worden niet overschreven;
- fouttypen onderscheiden minimaal validation, auth, rate limit, transient en permanent;
- de agent verzint geen IDs of assignments.

## 11. Deployment en configuratie

### 11.1 GitHub-first

De canonical repository is:

```text
bramvrensen/Hermes-Timesheet-Clerk
```

Installatie en updates verlopen via HERMES' pluginmechanisme vanaf GitHub. `main` is de deploybare branch tijdens de huidige bouwfase.

### 11.2 Eén codebase

De repository bevat uiteindelijk:

```text
Hermes-Timesheet-Clerk/
├── plugin.yaml
├── __init__.py
├── plugin.py
├── timesheet_clerk/        # gedeelde integratie/core
├── skills/timesheet-clerk/SKILL.md
├── frontend/               # Streamlit
├── docs/
└── tests/
```

De frontend mag technisch een apart proces zijn, maar hoeft niet beschikbaar te blijven wanneer HERMES zelf uitvalt. Beide vormen samen één functioneel product.

### 11.3 HERMES pluginconfig

De plugin gebruikt HERMES Keys / `requires_env` voor credentials:

```text
CLOCKIFY_API_KEY
CLOCKIFY_WORKSPACE_ID
CLOCKIFY_USER_ID
SIMPLICATE_BASE_URL
SIMPLICATE_API_KEY
SIMPLICATE_API_SECRET
SIMPLICATE_EMPLOYEE_ID
```

Secrets worden nooit naar plans, feedback, rules of logs geschreven.

### 11.4 Frontend route en login

De beoogde route is:

```text
https://<hermes-host>/timesheet
```

De pagina moet achter een login staan. Een eigen Clerk-login is toegestaan. De exacte Caddy-configuratie is deploymenttechniek en geen functionele businesslogica.

## 12. Open technische validaties vóór writes

Voor `simplicate_book_on_assignment(...)` moet nog tegen de live Simplicate API worden vastgesteld:

- of assignment booking een eigen endpoint/methode heeft of `POST /hours/hours` gebruikt;
- welke velden verplicht zijn;
- of project/service/hour type bij assignment booking hoeven te worden meegestuurd;
- response-ID en foutgedrag;
- ID-prefix- en timezone-quirks.

De eerder werkende Antigravity-code blijft een technische referentie, maar is niet automatisch het functionele ontwerp.

## 13. Bouwvolgorde

1. API-only integratielaag en HERMES plugin read-tools.
2. Live validatie Clockify/Simplicate reads en assignmentsemantiek.
3. Plan-, feedback-, rules- en receipt-schemas.
4. Plan repository/lifecycle/versioning.
5. Streamlit review-UI.
6. Feedback/learning persistence.
7. Validatie en bouw van assignment/direct write-paths.
8. Idempotente bookingflow.
9. End-to-end dry run.
10. Controlled activation van Simplicate writes.

## 14. Acceptatiecriteria

Het ontwerp is geslaagd wanneer:

- HERMES live Clockify- en Simplicate-context via de plugin kan lezen;
- geplande en alleen beschikbare assignments niet worden verward;
- de SKILL geen transportquirks kent;
- tools geen autonome businessbeslissingen nemen;
- Streamlit geen LLM/mappingpolicy bevat;
- weeknorm per week aanpasbaar is met 36 uur als default;
- assignment override via `Klant · Project · Assignment` werkt;
- assignment-keuze onderliggende mappingvelden read-only maakt;
- directe mapping alleen geldige cascades toont;
- feedback traceerbaar en append-only is;
- AUTO uitsluitend uit actuele SKILL-policy/evidence ontstaat;
- een retry geen dubbele booking veroorzaakt;
- approved planversies niet ongemerkt worden vervangen;
- frontend en plugin als één GitHub-versie worden ontwikkeld en gedeployed;
- writes pas worden geactiveerd na live validatie van de Simplicate assignment-bookingsemantiek.
