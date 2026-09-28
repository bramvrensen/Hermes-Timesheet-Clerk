# Timesheet Clerk V2

Timesheet Clerk haalt uren uit Clockify, maakt voorstellen voor Simplicate en laat je die in een webpagina beoordelen en boeken. V2 draait als een eigen applicatie, met een eigen Hermes-runtime en een eigen **Timesheet Clerk**-profiel. Je kunt ATLAS verwijderen of opnieuw installeren zonder de Timesheet Clerk-code, instellingen of gegevens te verwijderen.

Deze versie wordt ontwikkeld op **`feature/v2`**. De bestaande V1 staat nog op `main`. Installeer V2 eerst naast de bestaande installatie en controleer de overgenomen gegevens voordat je V1 verwijdert.

## Direct vanuit GitHub installeren

Gebruik een Linux-server met Docker, Docker Compose V2, Python 3 en curl. Er hoeft geen Hermes of ATLAS op die server te draaien.

```bash
curl -fsSL https://raw.githubusercontent.com/bramvrensen/Hermes-Timesheet-Clerk/feature/v2/install.sh -o /tmp/timesheet-clerk-install.sh
bash /tmp/timesheet-clerk-install.sh
```

De installer vraagt eenmalig om je Clockify- en Simplicate-verbindingen, een webwachtwoord en eventueel je modelverbinding. Hij downloadt de gekozen GitHub-versie, bouwt de applicatie met zijn eigen Hermes-runtime, maakt het Timesheet Clerk-profiel aan en wacht totdat de webpagina en verbindingsservice werken. Een Git-clone is niet nodig.

Standaard staat de installatie in `~/timesheet-clerk`. Open daarna **http://localhost:8501** op de server, of het webadres van je reverse proxy. Bij een externe server kun je tijdelijk een SSH-tunnel gebruiken; de [installatiehandleiding](docs/DEPLOYMENT.md) beschrijft dat.

Zonder model kun je **Import for manual review** gebruiken. Clockify wordt dan deterministisch ingelezen en alle nieuwe regels vragen om handmatige koppeling. Een model is alleen nodig voor automatische koppelingsvoorstellen.

## Bestaande Timesheet Clerk meenemen

Gebruik de volledige oude **Timesheet Clerk-gegevensmap**, met `config.json`, `SKILL.md`, `plans/`, `approvals/` en `receipts/`. Pauzeer de oude Timesheet Clerk-planner en webpagina terwijl je een consistente kopie maakt. Geef die map of een Timesheet Clerk-exportbestand mee aan de **eerste** V2-installatie:

```bash
bash /tmp/timesheet-clerk-install.sh --migrate-from /pad/naar/oude/timesheet-clerk
```

De import controleert de gegevens, bewaart plannen, boekingsbewijzen, feedback, regels en je eigen instructies, en laat de bron intact. Hij weigert een al gevulde V2-opslag te overschrijven. Hermes-sessies, algemene ATLAS-instructies en oude Hermes-geheimen worden niet geïmporteerd.

## Een nieuwe Hermes-installatie verbinden

Timesheet Clerk werkt al via zijn eigen webpagina. Wil je hem ook vanuit je nieuwe ATLAS/Hermes aanspreken, download dan op de machine waar Hermes draait het verbindingsprogramma:

```bash
curl -fsSL https://raw.githubusercontent.com/bramvrensen/Hermes-Timesheet-Clerk/feature/v2/connect-hermes.py -o /tmp/timesheet-clerk-connect.py
python3 /tmp/timesheet-clerk-connect.py
```

Dit programma vraagt het Timesheet Clerk-API-adres en je verbindingstoken, controleert de verbinding en maakt in die Hermes-installatie een **Timesheet Clerk**-profiel (`timesheet-clerk`) met zijn eigen verbindingsplugin en skill. Voor het model van dit nieuwe Hermes-profiel opent het de Hermes-modelkeuze. Je standaardprofiel blijft behouden. Het token staat in de privé `.env` van de Timesheet Clerk-installatie, onder `TIMESHEET_CLERK_API_TOKEN`.

Daarna open je het profiel met:

```bash
hermes -p timesheet-clerk
```

Vraag bijvoorbeeld: “Maak voorstellen voor 24 tot en met 30 augustus 2026.” De plugin kan de status opvragen, een week laten genereren en de voortgang bekijken. Beoordelen en boeken doe je in de Timesheet Clerk-webpagina. De nieuwe ATLAS heeft geen Clockify- of Simplicate-sleutels nodig.

Een normale native Hermes-plugininstallatie van deze **V2-repo** registreert eveneens alleen deze verbinding; die installeert de zelfstandige service of het aparte profiel niet. Gebruik de twee programma's hierboven voor de volledige automatische installatie.

## Updates en gegevens

Voer hetzelfde installatiecommando opnieuw uit om de laatste versie van `feature/v2` op te halen. Bestaande instellingen blijven behouden. Iedere codeversie krijgt een eigen map; de huidige versie wordt pas aangewezen nadat de service gezond is. Bij een mislukte start probeert de installer de vorige versie terug te starten. Ook een vast GitHub-commit of een tag is mogelijk via `--ref`.

De Docker-volumes `timesheet-clerk-v2-state` en `timesheet-clerk-v2-runtime` horen uitsluitend bij Timesheet Clerk. De Compose-installatie van ATLAS kan deze niet via haar eigen `down` verwijderen. Bewaar de Timesheet Clerk-installatiemap en deze volumes; een algemene `docker volume prune` kan ongebruikte volumes van alle applicaties verwijderen.

## Waar zit het model?

```text
Webpagina of Hermes-verbindingsplugin
                 ↓
Timesheet Clerk Python: brongegevens, context, verschillen en controles
                 ↓ alleen voor koppelingsvoorstellen
Eigen Hermes-profiel → ingestelde model-API
                 ↓ alleen beslissingen
Timesheet Clerk Python: validatie, planning, opslag en review
                 ↓ na een boekingsactie in de webpagina
Simplicate REST API → boekingsbewijs → controle door teruglezen
```

Het model kan geen uren boeken en krijgt geen Clockify- of Simplicate-sleutels. Python bepaalt bronintegriteit, weekindeling, tijden, samenvoeging, revisies, behoud van menselijke keuzes en boekingscontroles. Er is geen MCP-laag tussen Timesheet Clerk en Clockify/Simplicate. Zie [de V2-architectuur](docs/V2-ARCHITECTURE.md) voor de precieze codepaden en grenzen.

## Ontwikkeling en controles

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
PYTHONPATH=. .venv/bin/python -m pytest --rootdir=tests --import-mode=importlib -q tests
```

GitHub controleert daarnaast het echte Docker-image, de privé Hermes-toolketen met een lokale modeltest en het starten van Timesheet Clerk zonder ATLAS. Die tests doen geen live boekingen. Voor de definitieve migratie blijft een controle op je server met je eigen integraties nodig.
