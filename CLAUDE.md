# Scouting-værktøj til CS2

Analyseværktøj til modstanderscouting for en dansk esportforening med hold i
Esportligaen og POWER Ligaen. Bygges af én person som hobbyprojekt.

**Brugere:** 4–5 IGL'er og trænere i foreningen. Ingen andre.
**Bruges:** aftenen før en kamp, løbende i træningsugen, til selvanalyse og ved map veto.
**Sprog:** al UI og alle rapporter på dansk. Kode og kommentarer på dansk.

---

## Hvad det er

En web-app på en selvhostet maskine — ikke et program man downloader. Serveren
henter og parser demoer; IGL'en logger ind og læser en rapport per modstander per map.
Rapporten skal også kunne downloades og læses offline.

Grunden til web frem for desktop: parsing er tungt og skal ske på serveren, og den
delte modstanderdatabase på tværs af foreningens hold er hele værdien.

## Arkitektur

Fire dele, som skal kunne ændres uafhængigt:

```
downloader  →  parser  →  analyse  →  web
```

Downloaderen er den, der går i stykker når ligaen ændrer noget. Den skal kunne
repareres uden at røre resten.

**Hosting:** gammel gaming-PC med Ubuntu Server, kører 24/7 (~700–1500 kr/år i strøm).
Cloudflare Tunnel ud på nettet — ingen porte åbnet i routeren. Cloudflare Access
som login foran hele siden (gratis op til 50 brugere), så Streamlit/app-laget
ikke selv skal håndtere brugere. Domæne er købt.

**Note til når Ubuntu Server-maskinen sættes op:** skal kunne fjernstyres —
husk SSH (evt. nøglebaseret) fra starten af installationen, så den ikke skal
stå fysisk tilsluttet skærm/tastatur bagefter.

---

## Downloaderen — teknisk kortlagt

Hele kæden er verificeret. **Ingen login, ingen API-nøgle, ingen cookies.**

```
liga.dust2.dk/kampe        → HTML indeholder JSON med alle kampe
   ↓ challonge_id
/kampe/{id}/{slug}         → HTML indeholder cdn.overpass.dk ZIP-links (1–3 per kamp)
   ↓
cdn.overpass.dk/demos/...  → GET → pak ud → .dem
```

**Kamplisten** (`liga.dust2.dk/kampe`) har et JSON-objekt i HTML'en med:
- `ligaer` — alle brackets i sæsonen med holdliste og hold-ID
- `resultater` — hver kamp med `challonge_id`, begge hold, dato, map, score
- `stageInfo` per kamp — `branch: "wb"/"lb"`, rundenummer, dybde

**Kampsiden** har desuden gratis metadata, som ikke kræver parsing:
- veto-log struktureret med tidsstempler og hold-ID
- fuldt scoreboard per map med SteamID64, inkl. `first_kills_t/ct`,
  `first_deaths_t/ct`, `trade_kills`, `utility_damage`, `enemies_flashed`, `kast`
- `roundOverview` per map: vinder, overlevende per side, årsag
- `seasonData` med alle sæsoner og divisioner tilbage til sæson 14

**Udtræk med regex**, ikke ved at parse Next.js' RSC-struktur — den er bundet til
deres `buildId` og ændrer sig ved hver deploy.

### Regler for downloaderen

- **Kører dagligt**, ikke ugentligt. Demoer forsvinder efter 14 dage; dagligt giver
  13 chancer for at fange den samme kamp.
- **Idempotent.** Tjek `challonge_id` mod manifestet *før* download.
- **Manifest er sandheden**, ikke mappestrukturen. Én linje per hentet kamp med
  `challonge_id`, filstier, filhash, liga, division, dato, hold, map.
  Linjen skrives først når alle filer er på disken.
- **ZIP er mellemregning:** hent → pak ud → verificér at der er en `.dem` af
  fornuftig størrelse → slet ZIP. Fejler noget, markeres kampen ikke som hentet.
- **`.dem`-filer slettes aldrig.** De kan ikke hentes igen.
- **Download alt** fra alle divisioner, ikke kun egen liga. Disk er billigt;
  tabt data er permanent. Parse derimod kun on demand.
- **Ugentligt tjek** at filerne fra manifestet faktisk findes på disken.
- **Vær pæn:** 1–2 sek mellem kald, User-Agent med kontakt-mail, backfill om natten.

### Mappestruktur

```
demoer/powerligaen/2026-08-29_masq-vs-ecstatic/map1_ancient.dem
demoer/esportligaen/...
```

Ligaerne holdes adskilt — også i analysen, de slås **aldrig** sammen.
Division ligger i manifestet, ikke i stien, fordi hold rykker op og ned.

### Overvågning

`overvaagning.py` findes allerede: Discord-webhook, alarm efter 3 fejl i træk,
genvarsel højst hver 12. time, "kører igen"-besked, healthchecks.io som dødmandsknap.
Wrap downloaderen i `koer_job()`. Rejs `JobFejl` ved tavse fejl — fx 0 kampe fundet
hvor der burde være nogle, hvilket betyder at HTML-strukturen er ændret.

---

## Parsing

**awpy 2.0.2** (`pip install awpy`). Verificeret API:
- `Demo(path, tickrate=64)` — **awpy defaulter til 128; ligaen kører 64.**
  Bekræftet via radar-manifestet (`tps: 64`). Sættes det ikke, bliver alle
  tidsberegninger dobbelt så lange uden at fejle synligt.
- `dem.parse()` sætter `.rounds`, `.ticks`, `.events`; `.kills`, `.grenades`,
  `.smokes`, `.damages`, `.bomb`, `.shots`, `.infernos` er properties (Polars).
- `dem.rounds` har: `round_num`, `start`, `freeze_end`, `end`, `official_end`,
  `winner`, `reason`.
- Standard player_props inkluderer `X`, `Y`, `Z`, `health`, `team_name`, `side`
  og **`last_place_name`** — spillets eget callout-navn. Brug altid det;
  callouts må aldrig komme fra modellen.
- `awpy get maps` + `awpy get tris` henter radarbilleder og kortdata.
- Radar-koordinater: `x_radar = (x - pos_x) / scale`, `y_radar = (pos_y - y) / scale`.

**Nuke og Vertigo har to etager.** Positioner skal deles på z-koordinat, ellers
ligger B-spillerne oven i A-spillerne i både data og på kortet.

Parse on demand, cache resultatet som Parquet med demoens hash i filnavnet.
Downsample ticks til 4–8 Hz. Regn med 50–150 MB parsed per demo.

---

## Analysen — principper

Disse er vigtigere end noget andet i filen. De er resultatet af samtaler med
foreningens IGL'er.

### 1. Udløseren skal være noget, de kan se i kampen

"Når deres AWP står i Heaven ved 20 sek" er ubrugeligt — ved man det, har man
allerede peeket ham. Gyldige udløsere: utility der lander, et drab der er faldet,
deres køb, tid, score. Skjulte positioner er derimod fine som **konsekvens**.

### 2. Vi måler valg, ikke udfald

"Deres entry dør i Banana i 60 % af runderne" siger noget om modstanderen.
"Han tager peeken på Banana i 8 af 10 T-runder" er hans valg og er stabilt.
Alt hvor resultatet afhænger af modstanderen ryger ud.

### 3. Beskriv, dømm ikke

Værktøjet kan ikke se en spillers fornemmelse. En erfaren spiller peeker et sted,
der ser dumt ud på demoen, fordi han ved noget om modstanderen. Rapporten skriver
derfor "de flasher Banana i 8 af 10 runder", aldrig "dårlig flash".

**Men:** output må gerne måles. To drab er værdi. At have clearet Lobby er værdi,
fordi holdet nu ved, at der ikke kommer nogen gennem Hut eller Squeaky. Det kræver
ikke at gætte intention. Og hold må gerne sammenlignes med ligaen — "de forsvarer B
i 41 % mod divisionens 53 %" er beskrivelse, ikke dom.

### 4. Vis altid nævneren

Aldrig "de gør X". Altid: hvor mange gange udløseren skete, hvor tit konsekvensen
fulgte, og hvad basisraten er. Sortér efter afvigelse fra basisraten, ikke efter
hyppighed — det er der overraskelserne ligger.

### Tærskler

- Minimum **4 forekomster** af udløseren
- Mindst **70 %** konsekvens
- Mindst **25 procentpoint** over basisraten
- Skal overleve de nyeste 25 % af kampene, som søgningen ikke har set
- Tærsklen **kalibreres per hold** ved at køre samme søgning på bevidst blandet
  data og hæve kravet, indtil støjen er nede omkring et par fund
- Pistolrunder har lavere krav — der er kun to per kamp

**Roster-filter:** demoer indgår kun, hvis mindst 3–4 af holdets nuværende femmer
var på serveren. Match på SteamID64, aldrig holdnavn.

### Tre tillidsniveauer

**Bekræftet** (holder i tilbageholdte kampe) · **Sandsynligt** (stærkt, ikke testet)
· **Svagt** (over grænsen, men på niveau med støj — vises alligevel).

---

## Hvad rapporten indeholder

Per hold **og** map. Veto ligger på holdniveau.

1. **Setups som helhed** — hovedafsnittet. IGL'erne kan selv huske enkeltspillere;
   det de ikke kan, er at holde styr på hvordan fem positioner hænger sammen.
2. **Når fordelingen ændrer sig** — spiller de 3 midt i stedet for 2, hvad gør
   B-spillerne så? Direkte efterspurgt.
3. **Pistol, force og eco** — eget afsnit, alle nævnte det.
4. **Køb koblet til opstilling.**
5. **Spillerprofiler** bygget på adfærd, ikke leaderboard: hvem køber AWP og hvor,
   hvem er først gennem chokepoints, hvem kaster util for holdet, hvor konsekvent
   holdes positionen, afstand til holdkammerater (kan han tradet), hvornår han får
   kontakt, hvor tit han er i første duel. Skydetal nederst som kontekst.
6. **Svagheder** — sammenlignet med divisionen.
7. **Map veto** — kræver ingen demoer, kan bygges først.

**Færre fund, mere detaljeret.** IGL'erne var enige. Rangering skærer.

### Informationssporing (billig version, i v1)

Et drab eller en skade afslører information. Dør nogen til en spiller på Ramp, ved
holdet nu at der er en på Ramp. Det kræver ingen sigtelinje-beregning.
Det fanger det meste af "hvad vidste de, da de traf beslutningen".

### Flash-koordination

Det målbare er timing mellem holdkammerater: flash kastet, og under 2 sekunder
senere bevæger en makker sig gennem området. Det er koordination, uanset om
flashen virkede. Effektiviteten (`enemies_flashed`) tages med som **note ved siden af**,
ikke som hovedfundet.

---

## Efter version 1

I denne rækkefølge — begge er nu klart begrundede:

1. **Områdekontrol som funktion af tid.** Hvor lang tid tager det en T at nå Heaven
   fra der hvor han sidst blev set? Under 5 sek = ingen kontrol. Gør det målbart,
   hvornår kontrol forsvinder, og hvor meget et play er værd (mindre plads = højere
   indsats). Bruger awpys nav mesh.
2. **Sigtelinjer / hvem så hvem.** awpy har et visibility-modul.
3. Bevægelsesretning; executes genkendt som én handling; clustering frem for callouts.

---

## Rapportens udseende

`eksempel-rapport.html` findes som reference — én selvstændig fil med indlejrede
billeder, mørk baggrund, print-stylesheet der vender om til lys.

- Mørk baggrund, fordi radarudsnittene selv er mørke
- Farven (varm rødorange) er den, spillet bruger til bombesite-markering
- Positioner vises som **varmezoner** per spiller, ikke prikker på ét stort kort
- Udsnittet beregnes af, hvor spredt positionerne ligger — en spiller uden fast
  plads får automatisk et bredt udsnit, hvilket i sig selv er informationen
- Tillidsniveau kodes i stregtykkelsen over hvert fund
- Én bjælke per fund med lodret markør ved basisraten

---

## Åbne beslutninger

- **Hvordan impact måles per runde.** Hvad tæller som "information vundet", og
  hvordan vægtes det mod et drab?
- **Winrate-sammenligning:** mod holdets winrate på mappet, eller inden for samme
  rundetype? Sidstnævnte er mere retvisende, men ikke besluttet.
- **Hvor mange fund rapporten viser.** Ingen IGL gav et tal.
- **Datamodellen** — konkrete tabeller og felter. Lettest at skrive rigtigt efter
  et par demoer er parset.
- **Hvad sker der ved for lidt data.** Forslag: under 8 kampe med nuværende
  opstilling vises ingen mønstre, kun rå positionsdata og profiler, med tydelig note.

---

## Ting man ikke skal gøre

- **Tegn ikke kort i hånden.** Brug `awpy get maps` og koordinat-omregningen.
  Håndtegnede skematikker af Nuke blev prøvet to gange og var forkerte begge gange.
- **Slet ikke `.dem`-filer.** Nogensinde.
- **Sæt tickrate eksplicit til 64.**
- **Slå ikke ligaerne sammen.**
- **Byg ikke det fulde system før valideringen.** Kør analysen på et hold, IGL'en
  allerede kender, og se om outputtet matcher det, han ved. Hvis ikke, er enten
  analysen forkert eller datamængden for lille — begge dele er kritisk at vide først.

## Kontekst om adgang

Demoer ligger frit tilgængeligt for alle i 14 dage. Ejeren har som caster adgang
til et længere arkiv, men det bruges **kun til udvikling og test**, aldrig i den
færdige version — det ville være en interessekonflikt. Produktionsdata hentes
udelukkende inden for det vindue, alle andre også har.
