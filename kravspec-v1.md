# Modstanderrapport — hvad version 1 skal indeholde

Skrevet efter samtaler med IGL'erne. Det her er, hvad værktøjet bygges til at gøre, og hvad det bevidst ikke gør.

---

## To regler der gælder alt

**1. Udløseren skal være noget, I kan se i kampen.**

Et mønster er kun brugbart, hvis det, der udløser det, er noget I ved undervejs. Utility der lander. Et drab der er faldet. Deres køb. Tid og score.

Derimod ikke: skjulte positioner. "Når deres AWP står i Heaven ved 20 sekunder" er ubrugeligt — ved I det, har I allerede peeket ham, og så ved I det i forvejen.

Skjulte positioner er til gengæld gode som **konsekvens**. "Når de smoker Ramp tidligt, står B-anchoren et andet sted end normalt" virker, fordi udløseren er synlig og svaret er det, I gerne vil vide.

**2. Vi måler valg, ikke udfald.**

"Deres entry dør i Banana i 60 % af runderne" siger mest om, hvordan modstanderen spillede — ikke om holdet. Den brugbare version er: *han tager peeken på Banana i 8 ud af 10 T-runder*. Det er hans valg, og det er stabilt uanset hvem de møder.

Alt hvor resultatet afhænger af modstanderen, ryger ud af rapporten.

---

## Rapportens indhold

### 1. Setups — hovedafsnittet

IGL'erne nævnte alle det samme problem: enkeltspillere kan man godt huske, men det er umuligt at holde styr på, hvordan fem positioner hænger sammen. Det er der, værktøjet skal vinde.

Så rapporten viser ikke "hvor står anchoren". Den viser **hele opstillinger som enhed**:

> **B-setup nr. 2** — 11 af 34 CT-runder på Nuke
> Vises som kort med alle fem placeret

Og for hvert setup: hvad udløser det. Rundetype, køb, score, tidligere runder.

### 2. Når fordelingen ændrer sig

Direkte svar på det, flere efterspurgte: hvis de spiller tre midt i stedet for to, hvad gør B-spillerne så?

Rapporten tager hver "usædvanlig fordeling" og viser, hvad der sker det andet sted på mappet. Det er analysen, ingen kan lave i hovedet, og den bliver et fast afsnit.

### 3. Pistol, force og eco

Eget afsnit, fordi alle nævnte det.

Pistolrunde-opstilling og utility, T og CT. Runden efter en vundet pistol, runden efter en tabt. Er deres force den samme fra kamp til kamp. Hvad gør de på eco.

Her sænkes kravet til antal forekomster — der er kun to pistolrunder per kamp, så fire gange er ikke et rimeligt krav. Med 15 kampe er der 30 pistolrunder, og det rækker.

### 4. Køb koblet til opstilling

Gør de noget andet på en force end på et fuldt køb, ud over det åbenlyse? Står de andre steder, går de andre steder hen, kaster de anderledes.

### 5. Spillerprofiler

Se nedenfor — det er et afsnit for sig.

### 6. Map veto

Hvad banner de først, hvad ender de på, hvad vinder de på. Kræver ingen demoer og kan laves først.

---

## Om spillerprofiler

Et leaderboard viser, hvem der er god til at skyde. Det siger ikke, hvem man skal være bange for, og det siger slet ikke, hvad man skal gøre ved ham.

Så hver spiller får en profil bygget på, **hvad han vælger at gøre** — ikke hvad han rammer.

**Rolle**, udledt af opførsel frem for påstand:
- Hvem køber AWP, hvor tit, og hvilke positioner tager han med den
- Hvem er først gennem chokepoints, per map og side
- Hvem kaster utility for holdet på executes
- Hvem dropper til de andre

**Positioner**, med hvor konsekvent de holdes. En spiller der står samme sted i 90 % af runderne, kan man planlægge imod. En der varierer, kan man ikke — og det er i sig selv information værd at have.

**Afstand til holdkammerater.** Spiller han tæt nok til at blive tradet, eller står han alene? Det afgør, om det kan betale sig at tage duellen med ham.

**Hvornår han får kontakt.** Er han altid tidligt i runden eller sent. Det fortæller om han er entry eller lurker, uden at man skal gætte.

**Hvor tit han er i den første duel overhovedet.** Det er et valg. Om han vinder den er ikke.

Skydetallene kommer med, men nederst, og kun for at give kontekst. De er ikke det, profilen bygger på.

---

## Hvordan fund rangeres

Alle sagde det samme: hellere færre ting, mere detaljeret, og det de gør hyppigst.

Så rapporten er ikke en liste af alt, hvad søgningen finder. Det er et mindre antal opslag, hver med kort, tal og de runder det bygger på — rangeret efter **hvor tit det sker gange hvor meget det betyder for runden**, ikke efter hvor statistisk stærkt det er.

Hvert fund står med tre tal:

> 7 af 9 gange (78 %) — normalt sker det i 21 % af runderne

Og i tre grupper: **bekræftet** (holder også i de nyeste kampe, som søgningen ikke har set), **sandsynligt** (stærkt, men ikke testet endnu), **svagt** (over grænsen, men på niveau med tilfældighed).

En bemærkning: alle sagde, at ingen information er spild af tid. Det er rigtigt, når man læser én ting ad gangen. Det holder ikke for en rapport — kommer alt med, bliver intet læst. Så skæringen sker via rangering, og I kan altid folde resten ud.

---

## Ikke med i version 1

- Hvilken vej folk kigger
- Om en smoke faktisk blokerer en bestemt sigtelinje
- Executes genkendt som én samlet handling frem for løsrevne kast

Alle tre står øverst på listen bagefter. Grundlaget skal virke først.
