Analizza la conversazione recente e il game state.

OBIETTIVO
Estrarre cosa e' vero ADESSO nel presente (memoria a medio termine).
Questa review riconcilia chat <-> state, correggendo dati stale o rumorosi.
Non riscrivere il turno appena risolto salvo contraddizione chiara nella chat.
Non promuovere nulla in wiki: quello e' compito della consolidation review.

REGOLE GENERALI
- La chat batte il game state quando sono in conflitto.
- Non creare chiavi per fatti non ancora accaduti.
- Non inventare titoli, cariche, stati politici o entita' non emersi in chat.

---

PLAYER_LOCATION
Obbligatorio SE il giocatore ha cambiato posto rispetto al game state.
- Indica dove si trova FISICAMENTE ORA nella scena attuale, non la citta' di partenza.
- Usa id wiki gia' noti in chat/state; se non esistono, usa uno slug descrittivo.
- Se la chat mostra un luogo diverso da quello nello state, aggiorna: non lasciare lo slug vecchio.

CHARACTERS_ACTIVE
Obbligatorio in OGNI review, mai omesso, mai null.
- Lista COMPLETA e SOSTITUTIVA di chi e' fisicamente presente ORA con il PG.
- [] se il PG e' solo. Correggi presenze rimaste stale dal turno precedente.
- Usa id wiki se noti; altrimenti ruoli gia' emersi in chat. Mai inventare nomi propri.
- VIETATO includere il PG stesso (id, nome, "player"): sono solo NPC / ruoli terzi.

---

SITUATIONS — memoria a medio termine

Cosa sono: fatti ancora veri e rilevanti per le prossime scene — contesto aperto,
tensioni locali, obiettivi in corso, voci credute, relazioni o scenari non risolti,
stato di albi/registri/missioni/accordi (chi e' iscritto, posti liberi, requisiti).

Cosa NON sono: non e' il canone di lungo periodo (quello va in wiki, tramite
consolidamento), e non e' un log di ogni micro-azione.

TEST DI INCLUSIONE (usalo sia per aggiungere che per rimuovere):
Nelle prossime 2-3 scene, un NPC, documento o evento potrebbe fare riferimento a
questo fatto? Se mancasse, la scena risulterebbe incoerente (es. un NPC che
"dimentica" di essere gia' iscritto a qualcosa)? Se si a entrambe → includi/mantieni.
Se no → non aggiungere, o rimuovi se gia' presente.

situations_add — includi se superano il test sopra, per esempio:
- viaggio o permanenza in corso con peso narrativo ("in viaggio verso [luogo]",
  "ospite presso [luogo/gruppo]")
- voci o minacce locali aperte; incarichi, promesse, accordi non ancora chiusi
- tensione sociale attiva (diffidenza, allarme) che condiziona le scelte presenti
- stato di albo/gilda/missioni: iscrizioni, posti richiesti vs occupati, nomi gia'
  sul registro, requisiti ancora aperti
  Esempio: "Missione [nome]: [NPC A] gia' iscritto; servono altri 2 partecipanti"

situations_add — NON includere:
- gesti o battute isolate senza conseguenza ("ha salutato", "ha annuito")
- riflessioni interne o tono momentaneo del personaggio
- fatti gia' chiusi nella stessa scena
- eventi storici di grande portata da promuovere in wiki (distruzioni, morti di
  massa, cambi di reputazione stabili) — al massimo una riga sintetica se ancora
  rilevanti al presente locale, altrimenti lasciali al consolidamento

LIMITE: mantieni le situations attive indicativamente tra 5 e 12. Se il numero
cresce oltre, consolida voci simili in una sola invece di accumulare (es. tre
tensioni separate sullo stesso luogo possono diventare una voce piu' densa).

situations_remove — controlla sempre le situations gia' presenti nello state.
- Rimuovi cio' che non e' piu' vero, e' stato risolto, o e' diventato rumore.
- NON rimuovere stato di missioni/registri/iscrizioni solo perche' e' dettagliato:
  il criterio e' il test di inclusione sopra, non la lunghezza della voce.
- Usa stringhe ESATTE gia' presenti nello state quando rimuovi.
  Esempio: rimuovi "in viaggio verso X" se il PG e' gia' arrivato a X;
  rimuovi "in combattimento" se lo scontro si e' concluso.

---

CHARACTER_UPDATES / LOCATION_UPDATES (solo quando servono)
- character_updates: mood o relazione runtime per NPC gia' noti, se la chat lo mostra.
- location_updates: mappa id_luogo → oggetto {atmosphere?, objects?, events?}.
  objects ed events sono LISTE DI STRINGHE (es. ["bancone occupato", "bacheca"]),
  mai un dict {nome: descrizione}.
  Non mettere mai "atmosfera" come chiave di primo livello; non usare una stringa
  al posto dell'oggetto intero.
- Non inventare entita' o titoli nuovi.

EXTRA_SET / EXTRA_REMOVE
Solo per chiavi strutturate non previste altrove (es. wanted_level).
Non sovrascrivere i campi fissi dello schema.

FRONT_IMPACTS — solo strato 2 (interferenza locale su un intent gia' esistente):
null | distort | block + intent_id.
Esempio minimo: {"intent_id": "raid_locale", "effect": "distort",
"evidence": "PG ha allertato i difensori prima dell'imboscata"}
- Non usare per piani di arco globali (layer 3).
- Non aggiornare mai day, minutes o time: l'orologio e' gestito solo dal codice.

---

Restituisci SOLO JSON valido conforme a PresentReviewResult. Nessun testo fuori dal JSON.