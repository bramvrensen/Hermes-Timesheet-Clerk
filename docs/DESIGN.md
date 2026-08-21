# HERMES Timesheet Clerk — Definitief Functioneel Ontwerp

## 1. Doel en ontwerpprincipes

De Timesheet Clerk ondersteunt HERMES bij het voorbereiden, controleren, leren en boeken van uren uit Clockify naar Simplicate.

Kernprincipes:

1. **HERMES denkt.** De Timesheet Agent verzamelt context, interpreteert Clockify entries, kiest mappings, plant tijdvakken en bepaalt autonomie.
2. **Streamlit controleert.** De UI toont het plan, laat de gebruiker corrigeren en accorderen, registreert feedback en voert uitsluitend goedgekeurde boekingen uit.
3. **`booking_plan.json` is het contract.** Agent en UI communiceren niet via verborgen state of gedeelde businesslogica.
4. **`tools.py` is saai.** Tools abstraheren Clockify- en Simplicate-API's, normaliseren responses en verbergen alle API-quirks, ID-formattering, timezone-afwijkingen, pagination, retries en transportfouten.
5. **De SKILL bevat de policy.** Confidence-drempels, autonomievoorwaarden en generalisatieregels worden niet hardcoded in Python.
6. **Feedback is bewijs, geen directe wet.** Correcties worden append-only vastgelegd. De agent bepaalt volgens de SKILL of ze precedent, candidate rule of confirmed rule worden.
7. **Write-operaties zijn deterministisch.** Een goedgekeurd plan wordt exact uitgevoerd; tools mogen mappings of declarabiliteit niet stilletjes wijzigen.

## 2. Architectuur

```text
Clockify + Simplicate masterdata + relevante context
                       │
                       ▼
               HERMES Timesheet Agent
               ├─ SKILL policy
               ├─ confirmed_rules
               ├─ precedents
               └─ feedback history
                       │
                       ▼
                 booking_plan.json
                       │
                       ▼
                  Streamlit UI
               review / correct / approve
                    │             │
                    │             ▼
                    │       approved plan
                    │             │
                    ▼             ▼
             feedback_events   booking tools
                    │             │
                    └──────┐      ▼
                           │   Simplicate
                           ▼
                    volgende agent-run
```

## 3. Verantwoordelijkheden

### 3.1 HERMES Timesheet Agent

De agent:

- leest Clockify via tools;
- leest Simplicate masterdata en bestaande boekingen via tools;
- haalt aanvullende context op zoals voorgeschreven in de SKILL;
- leest relevante confirmed rules, precedenten en feedback;
- consolideert Clockify entries uitsluitend binnen dezelfde kalenderdag;
- maakt de sequentiële dagplanning;
- probeert per Clockify entry **eerst** een geldige Simplicate assignment van de gebruiker te vinden;
- gebruikt een passende assignment als voorkeurs-booking target;
- valt alleen terug op onafhankelijke klant → project → taak → uurcode-mapping wanneer geen geschikte assignment kan worden vastgesteld;
- bepaalt per veld of per assignment de autonomy tier en mapping source;
- maakt een overall entry tier uit de minst zekere noodzakelijke mapping;
- schrijft atomair een nieuw `booking_plan.json`.

De agent boekt niet tijdens het plannen.

### 3.2 Streamlit UI

Streamlit:

- leest één specifieke planversie;
- toont week-, dag- en entry-status;
- toont AUTO compact maar altijd uitklapbaar;
- laat uren, planning en mappings corrigeren;
- registreert elke materiële correctie als feedback-event;
- laat ASK/PROPOSE bevestigen;
- maakt een immutable approval snapshot;
- boekt alleen uit dat approved snapshot via tools;
- registreert per booking het resultaat.

Streamlit:

- haalt geen mappingcontext op voor eigen redenering;
- runt geen LLM;
- bepaalt geen confidence of autonomie;
- leert geen rules af;
- implementeert geen Simplicate-quirks.

#### 3.2.1 Weeknorm en urencontrole

De contractuele standaardweek is configureerbaar en staat voor de huidige inrichting standaard op **36,0 uur**.

De UI en het plan onderscheiden altijd:

- `contract_hours_default`: de normale contractweek;
- `target_hours`: de norm voor de specifieke week;
- geclockte uren;
- geplande/verantwoordbare uren;
- reeds geboekte uren;
- openstaande uren;
- verschil ten opzichte van `target_hours`.

`target_hours` is per week handmatig aanpasbaar in Streamlit. Alle waarschuwingen en volledigheidscontroles gebruiken `target_hours`, nooit rechtstreeks de standaard contracturen. Daarmee kunnen korte weken, verlof, feestdagen en andere afwijkingen worden verwerkt zonder de contractconfiguratie te wijzigen.

#### 3.2.2 Cascaderende handmatige mapping

Wanneer geen assignment wordt gebruikt, werkt de override-UI als een afhankelijke cascade:

```text
Klant → Project → Taak → Uurcode
```

Regels:

- na keuze van een klant toont Project uitsluitend projecten van die klant;
- na keuze van een project toont Taak uitsluitend taken/services van dat project;
- na keuze van een taak toont Uurcode uitsluitend geldige uurcodes voor die context;
- bij wijziging van een hoger niveau worden alleen onderliggende waarden gereset die niet langer geldig zijn;
- geldige bestaande keuzes blijven waar mogelijk behouden;
- Streamlit gebruikt hiervoor alleen deterministische masterdata-calls uit `tools.py`;
- Streamlit implementeert zelf geen Simplicate-querylogica of ID-quirks.

### 3.3 `tools.py`

`tools.py` bevat alleen integratie- en transportlogica.

Publieke capabilities zijn domeingericht, bijvoorbeeld:

- `clockify_get_time_entries(...)`
- `simplicate_get_context(...)`
- `simplicate_get_assignments(...)`
- `simplicate_get_booked_hours(...)`
- `simplicate_book_on_assignment(...)`
- `simplicate_book_direct(...)`

Intern mogen helpers bestaan voor:

- authenticatieheaders;
- pagination;
- retry/backoff;
- API error parsing;
- ID normalisatie en prefixing;
- service-ID legacy/UUID verschillen;
- timezone- en datumconversies;
- normalisatie van externe API-responses naar stabiele domeinobjecten.

Niet toegestaan in `tools.py`:

- LLM/Gemini-code;
- confidence/tier-bepaling;
- memory/rule matching;
- semantische classificatie;
- interne/billable keywordregels;
- agentpolicy;
- automatische mappingkeuzes.

API-quirks komen niet voor in de SKILL, booking plan of learned memory.

## 4. Leerloop en autonomie

### 4.1 Kennisniveaus

Het systeem onderscheidt vier soorten kennis.

#### Feedback event
Een onveranderlijk feit over een reviewactie, bijvoorbeeld: de agent stelde Service A voor en de gebruiker wijzigde dit naar Service B met een reden.

#### Precedent
Een eerder goedgekeurde concrete mapping. Een precedent is bewijs voor vergelijkbare gevallen maar geen algemene regel.

#### Candidate rule
Een door HERMES afgeleide mogelijke generalisatie uit feedback en/of precedenten. Een candidate rule mag maximaal PROPOSE ondersteunen tenzij de SKILL expliciet anders bepaalt.

#### Confirmed rule
Een voldoende bewezen en scoped regel die volgens de actuele autonomy policy AUTO mag ondersteunen.

De transitie is:

```text
feedback → precedent → candidate rule → confirmed rule
     ▲                                      │
     └──────── success/correction feedback ─┘
```

### 4.2 Append-only feedback

Alle reviewuitkomsten worden append-only opgeslagen, bij voorkeur in `feedback_events.jsonl`.

Een event bevat minimaal:

- `event_id`
- `timestamp`
- `plan_id`
- `entry_id`
- source fingerprint van de Clockify entry
- agent proposal
- reviewed values
- gewijzigde velden
- optionele `reason`
- oorspronkelijke mapping source en tiers
- outcome: `confirmed`, `corrected`, `skipped`

Historische feedback wordt nooit overschreven. Afgeleide rules mogen wel worden gedeactiveerd of vervangen.

### 4.3 Rule scope

Rules moeten expliciet aangeven waarop zij van toepassing zijn. Mogelijke scope-elementen:

- Clockify client;
- Clockify project;
- description exact/pattern/semantic intent;
- tags;
- Simplicate client/project context;
- eventueel andere door de SKILL toegestane context.

Een algemene beschrijving zoals `Projectoverleg` mag nooit door alleen herhaling een globale AUTO-rule worden.

### 4.4 Evidence en rule health

Een rule bewaart minimaal:

- `rule_id`
- `status`: candidate/confirmed/inactive
- `scope`
- `mapping`
- `created_at`
- `last_confirmed_at`
- `successful_applications`
- `corrections`
- `supporting_feedback_ids`
- optionele user reason / rationale summary

Een succesvolle AUTO-toepassing versterkt de evidence. Een correctie op AUTO is zwaar negatief bewijs en verlaagt volgens de SKILL onmiddellijk de autonomy tier van die rule of zet hem terug naar candidate/inactive.

### 4.5 Autonomy policy in SKILL

Python bevat geen businessdrempels zoals `confidence >= 0.70` of `override_count >= 2`.

De SKILL bepaalt onder andere:

- wanneer exact precedent voldoende is voor AUTO;
- welke minimum evidence een confirmed rule vereist;
- hoe match specificity wordt beoordeeld;
- hoe recency meeweegt;
- hoe conflicting evidence wordt behandeld;
- wanneer semantic similarity maximaal PROPOSE mag zijn;
- wanneer ontbrekende of invalide masterdata AUTO blokkeert;
- hoe snel een gecorrigeerde AUTO-rule wordt gedegradeerd;
- hoe confidence wordt geïnterpreteerd.

Confidence blijft een ondersteunend signaal, niet de primaire beslisregel.

### 4.6 Per-field autonomy

Autonomie wordt primair bepaald op het gekozen booking target:

- assignment, wanneer een assignment wordt gebruikt;
- anders per directe mappingcomponent:
  - klant/project;
  - taak/service;
  - hour type;
  - billable;
- eventueel duur wanneer de agent daarvan een voorstel maakt.

Wanneer een assignment is gekozen, worden project, taak/service en hour type beschouwd als afgeleid van die assignment en zijn zij geen afzonderlijke override-targets.

Voorbeeld:

```json
{
  "project": {"tier": "AUTO", "source": "confirmed_rule"},
  "service": {"tier": "AUTO", "source": "exact_precedent"},
  "hour_type": {"tier": "PROPOSE", "source": "project_context"}
}
```

De entry-tier is de laagste noodzakelijke tier. Een AUTO-entry kan dus alleen bestaan wanneer alle verplichte mappingvelden AUTO zijn.

### 4.7 Mapping sources

Elke mapping vermeldt de bron, bijvoorbeeld:

- `explicit_user_rule`
- `confirmed_rule`
- `exact_precedent`
- `similar_precedent`
- `project_context`
- `semantic_inference`
- `fallback`

De SKILL mag bronnen verschillend wegen. Semantic similarity alleen mag standaard niet tot AUTO leiden.

### 4.8 Conflict detection

Als meerdere geldige rules of precedenten elkaar tegenspreken:

- kiest de agent niet stilzwijgend één;
- verlaagt hij de betreffende tier;
- legt hij compact vast welke evidence conflicteert;
- vult hij `why_not_auto`.

### 4.9 `why_not_auto`

PROPOSE/ASK velden bevatten waar nuttig een compacte reden, bijvoorbeeld:

- `conflicting_rules`
- `new_client`
- `semantic_match_only`
- `missing_masterdata`
- `stale_precedent`
- `low_match_specificity`

Dit is bedoeld voor tuning en UI-uitleg, niet als chain-of-thought.

## 5. Data-contracten

### 5.1 `booking_plan.json`

Minimale top-level velden:

```json
{
  "schema_version": 1,
  "plan_id": "2026-W34-<uuid>",
  "revision": 1,
  "status": "DRAFT",
  "week_label": "2026-W34",
  "generated_at": "2026-08-21T18:00:00Z",
  "generated_by": "timesheet-clerk",
  "contract_hours": 36.0,
  "entries": []
}
```

Planstatus:

```text
GENERATING → DRAFT → IN_REVIEW → APPROVED → BOOKING → BOOKED
```

Een approved snapshot wordt nooit door een nieuwe agent-run overschreven.

### 5.2 Entry model

Een entry bevat minimaal:

- stabiele `entry_id`;
- Clockify source IDs;
- datum;
- geplande start/eindtijd;
- duur;
- beschrijving;
- source project/client/tags voor zover beschikbaar;
- `booking_mode`: `assignment` of `direct`;
- assignment-identiteit en leesbare context indien `booking_mode = assignment`;
- directe mappingwaarden indien `booking_mode = direct`;
- per-target/per-field tier/source/confidence;
- overall tier;
- compact rationale/provenance;
- `why_not_auto` indien van toepassing;
- signalen/conflicten;
- reviewstatus;
- bookingstatus.

### 5.3 Plan versioning en concurrency

- Nieuwe agent-run maakt een nieuwe `plan_id` of revision; hij overschrijft geen actief reviewplan.
- Streamlit opent expliciet één `plan_id` + revision.
- Bij save/approve controleert Streamlit dat dezelfde revision nog actueel is.
- Bij mismatch wordt de gebruiker gewaarschuwd en wordt niet blind geschreven.
- Schrijven gebeurt atomair: temp file + rename/replace.

## 6. Review, approval en booking

1. Streamlit opent een DRAFT en markeert die IN_REVIEW.
2. Correcties worden in review-state vastgelegd en als feedback events geregistreerd.
3. Approval maakt een immutable snapshot met eigen hash/version.
4. Booking gebruikt uitsluitend het approved snapshot.
5. Alleen dit snapshot wordt naar de booking tools gestuurd.
6. Bij `booking_mode = assignment` gebruikt Streamlit uitsluitend de assignment-booking capability.
7. Bij `booking_mode = direct` gebruikt Streamlit uitsluitend de directe booking capability.
8. De tool valideert technische input en boekt exact het gekozen booking target.
9. Elk bookingresultaat wordt vastgelegd met externe Simplicate ID of foutstatus.
10. Bij gedeeltelijke fout wordt niet blind de hele batch herhaald.

## 7. Assignment-first booking model

### 7.1 Assignment als primair booking target

Een Simplicate assignment representeert de koppeling tussen medewerker, project, taak/service en uursoort. Daarom is assignment matching de eerste route voor iedere Clockify entry.

De functionele beslisvolgorde is:

```text
Clockify entry
    ↓
Zoek geldige assignments voor gebruiker + relevante datum/periode
    ↓
Kan HERMES één passende assignment betrouwbaar bepalen?
    ├─ Ja  → booking_mode = assignment
    └─ Nee → booking_mode = direct
             Klant → Project → Taak → Uurcode
```

Een assignment mag zowel automatisch door HERMES worden gekozen als handmatig door de gebruiker worden geselecteerd tijdens review.

### 7.2 UI-regels voor assignment booking

Wanneer `booking_mode = assignment`:

- toont Streamlit een assignment-dropdown;
- de dropdownlabels bevatten minimaal **Klant · Project · Assignment**, zodat gelijknamige assignments herkenbaar zijn;
- klant, project, taak/service en uurcode worden als afgeleide read-only informatie getoond;
- deze onderliggende velden zijn niet afzonderlijk selecteerbaar of wijzigbaar;
- een override bestaat uit:
  - een andere assignment kiezen; of
  - expliciet overschakelen naar `booking_mode = direct`.

Wanneer wordt overgeschakeld naar `direct`, verschijnt pas de cascaderende klant → project → taak → uurcode-UI.

### 7.3 Learning op booking mode

Feedback registreert ook wijzigingen van booking mode en assignmentkeuze. Voorbeelden:

- assignment A → assignment B;
- direct mapping → assignment B;
- assignment A → direct mapping;
- assignment bevestigd zonder wijziging.

Deze feedback mag door de agent worden gebruikt om toekomstige assignment matching te verbeteren.

### 7.4 Autonomie en assignments

Assignments zijn een sterke bron van context en evidence. De SKILL bepaalt wanneer een assignment-match AUTO, PROPOSE of ASK mag zijn.

Harde regel:

> Een entry mag niet AUTO zijn wanneer een relevante assignment bestaat maar HERMES niet eenduidig kan vaststellen welke assignment moet worden gebruikt.

### 7.5 API-contract en validatie vóór implementatie

De UI en SKILL kennen niet de technische vorm van assignment booking in Simplicate.

`tools.py` exposeert twee afzonderlijke domeincapabilities:

```text
simplicate_book_on_assignment(...)
simplicate_book_direct(...)
```

Of deze onder water verschillende endpoints, methods of payloads gebruiken is uitsluitend een verantwoordelijkheid van de integratielaag.

**Voor daadwerkelijke bouw van `simplicate_book_on_assignment(...)` moet de bestaande Antigravity-implementatie en/of een gecontroleerde call tegen de echte Simplicate API worden gebruikt om vast te stellen:**

- of assignment booking via een aparte API-method/endpoint verloopt;
- welke velden daarbij verplicht zijn;
- of project, taak/service en hour type bij assignment booking geheel uit de assignment worden afgeleid;
- welke response-ID en foutcodes relevant zijn;
- welke Simplicate-specifieke ID- en timezone-quirks gelden.

Deze technische uitkomst wordt daarna uitsluitend in `tools.py` vastgelegd. De functionele architectuur verandert hierdoor niet.

## 8. Reconciliatie en idempotency

Reconciliatie is deterministisch en staat los van mapping-intelligentie.

### 8.1 Matchsterkte

Voorkeursvolgorde:

1. expliciete source/reference-identificatie tussen lokale booking en Simplicate, indien technisch mogelijk;
2. eerder opgeslagen lokale booking receipt met Simplicate ID;
3. sterke samengestelde fingerprint;
4. alleen wanneer uniek: datum + project + service + hour type + duur + note/fingerprint.

Een ambigue match wordt nooit automatisch `BOOKED`; hij wordt als reconciliation conflict gesignaleerd.

### 8.2 Booking receipts

Na iedere succesvolle write wordt lokaal minimaal opgeslagen:

- `plan_id`
- `entry_id`
- Clockify source IDs
- goedgekeurde mapping
- datum/duur
- Simplicate response ID
- timestamp

Deze receipts zijn de primaire lokale bescherming tegen dubbelboeken en maken veilige retries mogelijk.

## 9. Timeline en consolidatie

Clockify consolidatie mag uitsluitend plaatsvinden wanneer entries:

- op dezelfde lokale kalenderdag vallen;
- dezelfde relevante source-identiteit hebben volgens de SKILL/toolcontracten.

Entries op verschillende dagen worden nooit samengevoegd.

De agent maakt de initiële sequentiële planning. Streamlit mag na een handmatige duurwijziging puur deterministisch alle volgende tijdvakken van diezelfde dag verschuiven. Dat is presentatie/rekenlogica, geen mappingintelligentie.

## 10. Fail-safe gedrag

- Ongeldige/ontbrekende masterdata blokkeert booking voor de betreffende entry.
- Een conflict in learned rules verlaagt autonomie, nooit verhoogt die.
- Een technische API-fout verandert geen plan of learning state alsof de boeking gelukt is.
- Een gedeeltelijke batchbooking behoudt per-entry status.
- Een nieuwe planversie overschrijft nooit een review/approval snapshot.
- De tool-laag retourneert onderscheid tussen validation, auth, rate-limit, transient en permanent errors zodat de caller veilig kan beslissen over retry.

## 11. Packaging, deployment, hosting en authenticatie

De Timesheet Clerk wordt als **één versieerbaar project en één GitHub-repository** gebouwd en vanuit die repository in de HERMES-omgeving geïnstalleerd. De Clerk vormt functioneel één geheel met HERMES: zonder de agent is er geen plan/learning-loop en zonder de review-UI is er geen approval- en bookingflow. Onafhankelijke beschikbaarheid van de frontend wanneer HERMES uitvalt is daarom geen requirement.

De codebase bevat minimaal:

```text
Hermes-Timesheet-Clerk/
├── plugin / HERMES-integratie
├── skill / SKILL.md
├── shared API clients en domeincontracten
├── Streamlit frontend
├── docs/
│   └── DESIGN.md
└── tests/
```

De exacte Python-package-indeling mag tijdens implementatie worden verfijnd, zolang de verantwoordelijkheidsgrenzen uit dit ontwerp behouden blijven.

### 11.1 GitHub als source of truth

De GitHub-repository is de canonical source voor code én documentatie. Installatie en updates op de VPS worden vanuit deze repository uitgevoerd.

Eisen:

- één Clerk-versie omvat plugin/tools, SKILL, gedeelde integratiecode en frontend;
- plugin en frontend mogen technisch als afzonderlijke processen draaien, maar worden samen versieerd en gedeployed;
- wijzigingen in functioneel gedrag of architectuur vereisen in dezelfde change een update van `docs/DESIGN.md`;
- chatcontext is nooit de enige bron van een ontwerpbeslissing;
- secrets en runtime-state worden nooit naar GitHub gecommit.

### 11.2 HERMES plugin en SKILL

De HERMES-integratie wordt als installeerbare plugin/package geleverd. De plugin exposeert uitsluitend de tools/capabilities die de agent nodig heeft.

De Timesheet SKILL bevat domeinlogica, autonomy policy, learning policy en plan-generation instructies. API-transportdetails blijven uitsluitend in de integratielaag.

De agent krijgt geen vrij beschikbare capability om tijdens plan generation uren naar Simplicate te schrijven. Simplicate writes worden uitsluitend vanuit de goedgekeurde bookingflow uitgevoerd.

### 11.3 Gedeelde integratielaag

Plugin en frontend gebruiken dezelfde Clockify- en Simplicate-clients. Hierdoor bestaan API-quirks, normalisatie, retries, pagination en foutafhandeling maar op één plek.

De integratielaag exposeert domeingerichte read-capabilities aan HERMES en booking-capabilities aan de approval/bookingflow. De onderliggende REST-implementatie blijft voor SKILL en UI verborgen.

### 11.4 Runtime-state

Persistent runtime-state staat buiten de GitHub checkout/package, onder een HERMES-beheerde timesheet-directory, bijvoorbeeld:

```text
/home/hermes/.hermes/timesheet/
├── config.json
├── booking_plan.json
├── feedback_events.jsonl
├── rules.json
├── booking_receipts.jsonl
└── approval_snapshots/
```

Secrets worden apart opgeslagen en nooit in plan-, feedback-, rule- of receipt-bestanden geschreven.

### 11.5 URL en reverse proxy

De review-UI is bereikbaar onder:

```text
https://hermes.bramvanrensen.nl/timesheet
```

Caddy routeert `/timesheet` en alle benodigde onderliggende assets/WebSocket-verzoeken naar de Timesheet Clerk frontend. Overige HERMES-routes blijven ongewijzigd.

De exacte Caddy-syntax is deploymenttechniek en geen onderdeel van de functionele architectuur.

### 11.6 Netwerkbinding

De frontend luistert uitsluitend op localhost, bijvoorbeeld `127.0.0.1:8501`. Externe toegang verloopt uitsluitend via Caddy/TLS.

### 11.7 Eigen authenticatie

De Timesheet Clerk gebruikt voor de eerste versie een eigen login. Hergebruik van de HERMES-session is geen requirement.

Minimale eisen:

- login verplicht vóór timesheet-data of functies zichtbaar zijn;
- wachtwoorden nooit plaintext opgeslagen;
- geschikte salted password hash;
- sessie-expiry configureerbaar;
- sessiecookies minimaal `HttpOnly`, `Secure` en `SameSite=Lax`;
- logout maakt de actieve sessie ongeldig;
- één lokaal Clerk-account is voor v1 voldoende.

### 11.8 Procesbeheer en lifecycle

De frontend mag als apart proces/service draaien omdat Streamlit een webserver nodig heeft. Dit proces is echter onderdeel van dezelfde Timesheet Clerk deployment en versie.

Er is geen requirement dat de frontend operationeel blijft wanneer HERMES zelf niet beschikbaar is. Sterke functionele koppeling tussen beide is acceptabel en gewenst boven kunstmatige onafhankelijkheid.

De deployment moet wel voorkomen dat een frontend- en pluginversie uit verschillende releases ongemerkt samen worden gebruikt.

## 12. Bouwvolgorde

1. Refactor `tools.py` tot API-only integratielaag zonder businesslogica.
2. Valideer assignment booking tegen de bestaande Antigravity-code en de echte Simplicate API; leg de technische methode uitsluitend vast in `tools.py`.
3. Definieer schemas voor plan, feedback events, rules en booking receipts.
4. Bouw plan repository met atomair lezen/schrijven en lifecycle/version checks.
5. Bouw Streamlit om uitsluitend `booking_plan.json` te consumeren.
6. Bouw review-feedback en immutable approval snapshots.
7. Bouw idempotente bookingflow en receipts.
8. Schrijf de Timesheet SKILL met autonomy policy en learning workflow.
9. Koppel agent aan contextbronnen en plan generation.
10. Test eerst plan → review → dry-run booking.
11. Activeer daadwerkelijke Simplicate writes na succesvolle end-to-end test.

## 13. Acceptatiecriteria

Het ontwerp is geslaagd wanneer:

- Streamlit kan functioneren zonder enige LLM- of mappingcode;
- de SKILL geen Simplicate/Clockify transportquirks kent;
- tools geen autonome businessbeslissingen nemen;
- een correctie traceerbaar als feedback-event bestaat;
- HERMES rules kan opbouwen, versterken en degraderen;
- AUTO uitsluitend uit de SKILL-policy voortkomt;
- een plan tijdens review niet ongemerkt kan worden vervangen;
- een retry geen dubbele boeking veroorzaakt;
- dezelfde Clockify entry op verschillende dagen nooit door consolidatie verschuift naar één dag;
- `/timesheet` alleen na succesvolle Clerk-login toegankelijk is;
- Streamlit uitsluitend via localhost bereikbaar is en extern alleen via Caddy wordt ontsloten;
- plugin, SKILL, integratielaag en frontend als één Clerk-versie vanuit GitHub worden beheerd en gedeployed;
- de standaard weeknorm 36,0 uur bedraagt maar per week als `target_hours` aanpasbaar is;
- directe overrides uitsluitend geldige cascades tonen van klant → project → taak → uurcode;
- assignment matching altijd vóór directe mapping wordt geprobeerd;
- een gekozen assignment klant/project/taak/uursoort read-only maakt in de UI;
- een assignment handmatig via een duidelijk gelabelde `Klant · Project · Assignment` dropdown kan worden ge-override;
- assignment booking en directe booking technisch gescheiden tool-capabilities gebruiken.
