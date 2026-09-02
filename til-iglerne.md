# Modstanderanalyse — hvad synes I der mangler?

Jeg er i gang med at bygge et værktøj, der automatisk henter demoer fra vores ligaer og finder mønstre i, hvad modstanderne gør. Målet er, at I aftenen før en kamp kan åbne en rapport på det hold, I skal møde, i stedet for at sidde og spole demoer igennem.

Inden jeg bygger det færdigt, vil jeg gerne vide, om jeg er ved at bygge det rigtige. Læs igennem og sig, hvad der mangler — særligt i sidste afsnit.

---

## Hvad det finder

Værktøjet leder ikke efter bestemte ting. Det gennemgår alt, hvad der sker i et holds runder, og finder de sammenhænge, der går igen. Nogle eksempler på, hvad der kan komme ud:

- Når de smoker Ramp inden for de første 15 sekunder, går de B i 8 ud af 10 tilfælde
- Når deres AWP'er står i Heaven ved 20 sekunder, står nummer to altid i CT-spawn
- Efter en tabt pistolrunde force-buyer de i 9 ud af 11 tilfælde
- På Nuke CT har de kun én på B i under-runder, men to når de er foran
- Deres entry dør i Banana i 60 % af T-runderne på Inferno

Det er ikke en liste, jeg har programmeret. Det er den slags, søgningen finder af sig selv. Hvis de har en vane, jeg aldrig ville have tænkt på at lede efter, bør den også dukke op.

Til hvert fund hører et kort over mappet, hvor man kan se, hvor spillerne står, og hvor deres utility lander.

---

## Hvordan I skal læse tallene

Hvert fund står med tre tal:

> **Når `crax` står i Heaven ved 20 sek, står `toby` i CT-spawn**
> 7 af 9 gange (78 %) — normalt står han der i 21 % af runderne

Det midterste tal er, hvor tit det holder. Det sidste er, hvor tit det ville ske alligevel. Forskellen mellem dem er det, der gør fundet interessant.

Rapporten er delt i tre:

**Bekræftet** — mønsteret er fundet i deres ældre kampe og holder stadig i de nyeste. Det er dem, I kan spille efter.

**Sandsynligt** — ser stærkt ud, men der er ikke nok nye kampe til at teste det endnu.

**Svagt** — over grænsen, men på niveau med, hvad rent tilfælde ville producere. Vist alligevel, fordi I nogle gange kan genkende noget ægte i det, som en maskine ikke kan.

Grunden til opdelingen er, at hvis man leder efter mange nok ting, finder man altid noget, der ser ud som et mønster. Værktøjet forsøger at holde det fra hinanden, i stedet for at lade som om alt er lige sikkert.

---

## Hvad det ikke kan i første omgang

Værktøjet kan kun finde mønstre i det, det kan se. I første version kan det se:

positioner og callouts på faste tidspunkter i runden · al utility, hvor den landede og hvornår · hvem der dræbte hvem, hvor og med hvad · bombeplants · våben ved rundestart · scoreline og rundetype

Det kan **ikke** endnu:

- Se hvilken vej folk kigger, altså om de holder en vinkel eller er på vej et sted hen
- Regne på om en smoke rent faktisk blokerer en bestemt sigtelinje
- Genkende at fire utility-kast plus en bevægelse er én samlet execute, frem for fem løsrevne ting

De tre står øverst på listen bagefter. Jeg vil bare gerne have grundlaget til at virke først.

---

## Det jeg gerne vil have svar på

Det her er den vigtigste del. Svar gerne kort — jeg skal bruge jeres svar, ikke en rapport.

**1. Tænk på sidste gang du forberedte en kamp. Hvad brugte du tiden på?**

**2. Hvad ville du gerne have vidst om modstanderen, som du ikke kunne finde ud af?**

**3. Hvad brugte du tid på, som viste sig at være ligegyldigt?**
Det er nok det mest værdifulde spørgsmål, og det man aldrig stiller.

**4. Kig på eksemplerne øverst. Hvilke af dem ville du faktisk gøre noget ved — og hvilke ville du bare nikke til og glemme?**

**5. Hvor mange fund kan du overskue?**
Er 10 stykker på en side bedre end 40 med flere detaljer? Værktøjet finder formentlig langt flere, end nogen gider læse, så jeg skal vide, hvor grænsen går.

**6. Er der noget ved map veto, du gerne vil have med?**
Den del kræver ikke demoer og kan laves først. Hvad banner de, hvad ender de på, hvad vinder de på.

---

Sig endelig til, hvis noget lyder som spild af tid. Det er nemmere at skrotte nu end om tre måneder.
