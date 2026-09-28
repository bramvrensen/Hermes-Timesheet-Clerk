# Timesheet Clerk V2 installeren in Hermes

De plugin in deze repo is vanaf V2 een verbinding naar een zelfstandige Timesheet Clerk-service. Hij vraagt uitsluitend `TIMESHEET_CLERK_API_URL` en `TIMESHEET_CLERK_API_TOKEN`. Clockify, Simplicate, plannen, instructies en boekingshistorie blijven bij die service.

Gebruik eerst de zelfstandige installer en daarna `connect-hermes.py`, zoals beschreven in de [README](README.md). Het verbindingsprogramma maakt automatisch een eigen Timesheet Clerk-profiel met de verbindingsskill aan. Een native `hermes plugins install` registreert alleen de plugin in het gekozen bestaande profiel.

De beschikbare tools zijn:

- `timesheet_clerk_status`: status, actueel planoverzicht en reviewlink;
- `timesheet_clerk_generate`: een week laten genereren of verversen;
- `timesheet_clerk_job`: wachten op de uiteindelijke status van een gestart werk.

De verbinding boekt geen uren. Gebruik de zelfstandige webpagina om voorstellen te beoordelen en uren te boeken. Een vervangen of tijdelijk uitgeschakelde ATLAS heeft geen invloed op die webpagina of op haar eigen planner.
