# Timesheet Clerk V2 deployment

## Installatie

Vereist: Linux, werkende Docker-daemon, Docker Compose V2 met `up --wait`, Python 3 en curl. De eerste build downloadt de afhankelijkheden. Er is geen bestaande Hermes nodig.

```bash
curl -fsSL https://raw.githubusercontent.com/bramvrensen/Hermes-Timesheet-Clerk/feature/v2/install.sh -o /tmp/timesheet-clerk-install.sh
bash /tmp/timesheet-clerk-install.sh --dir "$HOME/timesheet-clerk"
```

De installer haalt eerst de SHA van de gekozen GitHub-ref op, downloadt het archief van die SHA en bouwt dat image. `--ref feature/v2` is de huidige standaard; een tag of SHA werkt ook. Met `--env-file /pad/private.env --yes` kan een eerste installatie zonder vragen draaien. Gebruik daarvoor een ingevulde versie van `.env.example`, inclusief een willekeurig API-token van minstens 24 tekens.

```text
~/timesheet-clerk/
├── .env                    privé instellingen, mode 0600
├── installation.json       geïnstalleerde GitHub-versie
├── current                 verwijzing naar de werkende codeversie
└── releases/<commit>/      code, Compose en verbindingsprogramma

Docker-volume timesheet-clerk-v2-state    → /data/clerk
Docker-volume timesheet-clerk-v2-runtime  → /data/hermes
```

Compose heeft een eigen projectnaam en volumes. Het image bevat Python, de webpagina, de API en een vastgezette Hermes-runtime. De container draait met gebruiker 10001; Docker init ruimt kindprocessen op. Beide interne endpoints moeten werken voordat de installer meldt dat Timesheet Clerk gestart is.

## Webpagina en verbinding bereikbaar maken

De hostpoorten zijn standaard uitsluitend gebonden aan `127.0.0.1`: webpagina 8501 en verbindings-API 8502. Voor een tijdelijke verbinding met een externe server:

```bash
ssh -L 8501:127.0.0.1:8501 -L 8502:127.0.0.1:8502 gebruiker@server
```

Open lokaal `http://localhost:8501`. Voor een vaste installatie kan een reverse proxy die op de host draait bijvoorbeeld twee HTTPS-adressen doorsturen:

```caddyfile
timesheet.example.nl {
    reverse_proxy 127.0.0.1:8501
}
timesheet-api.example.nl {
    reverse_proxy 127.0.0.1:8502
}
```

Een proxy in een Docker-container kan de host-loopback niet gebruiken: verbind die met een apart gedeeld netwerk of een hostgateway die toegang heeft tot deze poorten. Stem dit af op je bestaande proxy; die configuratie is geen onderdeel van de Timesheet Clerk-installer. Zet `TIMESHEET_CLERK_PUBLIC_URL` op het webadres. Geef `connect-hermes.py` het **API-adres**, bijvoorbeeld `https://timesheet-api.example.nl`. Als Hermes in een andere container draait, is `localhost` die container zelf.

De webpagina gebruikt haar eigen wachtwoord. De API gebruikt een apart Bearer-token. `/healthz` is openbaar en geeft alleen servicenaam en versie. De API heeft geen boekings-, verwijderings- of rebuild-endpoint.

## Van V1 naar V2

Maak een consistente kopie van de oude Timesheet Clerk-state terwijl de oude planner en Timesheet Clerk-webpagina niet schrijven. Veel V1-installaties gebruiken `/home/hermes/.hermes/timesheet-clerk`; oudere installaties gebruiken `/home/hermes/.hermes/profiles/atlas/timesheet-clerk`. Het is uitsluitend de Timesheet Clerk-map die nodig is.

```bash
bash /tmp/timesheet-clerk-install.sh --migrate-from /pad/naar/kopie/timesheet-clerk
```

De import vindt plaats vóór de eerste service-start, in een tijdelijk gecontroleerde map. Daarna worden gevalideerde bestanden naar de nieuwe opslag verplaatst. De bron blijft ongewijzigd. Een onderbroken verplaatsing kan met hetzelfde importcommando hervat worden; een gevulde bestemming wordt niet overschreven. Geïmporteerde bestanden krijgen de rechten van de eigen containergebruiker.

Meegenomen: configuratie, eigen `SKILL.md`, actieve-planwijzer, alle aangeleverde planrevisies en approvals, boekingsbewijzen, feedback, regels en eventuele V2-boekingspogingen. Niet meegenomen: Hermes-profiel, Hermes-sessies, `.env`, frontend- of plannerprocessen en cachebestanden. Het nieuwe plannerprofiel wordt altijd `timesheet-clerk`; overige geldige beleidsinstellingen en eigen instructies blijven behouden.

Controleer vóór het verwijderen van V1: planoverzicht en aantallen, een eerder beoordeelde regel, een bestaande boeking met bewijs, een refresh en de toegang vanuit je nieuwe Hermes. De automatische tests gebruiken testgegevens en vervangen deze controle met je eigen accounts niet.

## Instellingen en updates

Integration- en modelgeheimen staan in de private `.env` buiten de code. De webpagina bewaart beleidsinstellingen en mappinginstructies in het state-volume. Bewerk model/verbindingen in `.env` en voer de installer opnieuw uit om de containeromgeving te vernieuwen. Een lege `TIMESHEET_CLERK_MODEL` geeft handmatige review; `TIMESHEET_CLERK_SIMPLICATE_WRITE_ENABLED=false` blokkeert alle V2-webboekingen.

Updates bouwen eerst een nieuw image. De vorige codeversie blijft beschikbaar en de volumes blijven behouden. Bij een mislukte service-start probeert de installer de vorige versie opnieuw te starten. De `current`-verwijzing wordt alleen na een gezonde start aangepast. Gebruik geen `down --volumes` als je gegevens wilt behouden.

## Backup en herstel

Maak een export terwijl Timesheet Clerk niet actief wordt gebruikt voor review/boeken:

```bash
TIMESHEET_CLERK_ENV_FILE="$HOME/timesheet-clerk/.env" docker compose --env-file "$HOME/timesheet-clerk/.env" -f "$HOME/timesheet-clerk/current/compose.yaml" exec timesheet-clerk \
  python -m timesheet_clerk.migration export /data/clerk /data/clerk/timesheet-clerk-backup.tar.gz
```

Kopieer het exportbestand uit de container en bewaar ook je private `.env` apart. Het exportbestand bevat uitsluitend de bekende statebestanden en geen geheimen uit `.env`. Een backup kan met `--migrate-from /pad/timesheet-clerk-backup.tar.gz` naar een lege V2-installatie worden geïmporteerd. De import weigert symlinks, speciale bestanden, ongeldige paden en ongeldige JSON/plancontracten.

Het Hermes-runtimevolume bevat herbouwbare profielconfiguratie en plannerlogs; de boekingshistorie staat in het state-volume. Bewaar beide volumes bij een herstart. Een algemene Docker-prune is niet beperkt tot ATLAS en vereist dus aandacht voor Timesheet Clerk-volumes.
