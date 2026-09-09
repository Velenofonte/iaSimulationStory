Analizza game state e conversazione recente.

OBIETTIVO
Promuovere in wiki solo cio' che conta nel lungo periodo. Questa e' memoria
PERMANENTE: cio' che sopravvive anche quando la memoria a medio termine
(situations) viene ripulita. La consolidazione NON deve scrivere nella chat.

REGOLE GENERALI
- Non promuovere titoli o stati politici come fatti acquisiti se non sono
  ancora pubblici in scena.
- Non inventare magie, skill o poteri non emersi in chat o gia' in scheda.
- Non creare canone di setting assente dalla chat.

---

CHARACTER_UPDATES — scheda del giocatore

OBBLIGATORIO: la chiave e' sempre il player_id (es. "prova"), mai i campi in
piano. Formato:

```json
"character_updates": {
  "<player_id>": {
    "memories_add": ["..."],
    "memories_remove": ["..."],
    "spells_add": ["Nome — descrizione"],
    "open_threads_add": ["..."],
    "open_threads_remove": ["..."],
    "location": "id-luogo-attuale"
  }
}
```

MEMORIES_ADD — alta densita', pochi fatti (0–3 voci per consolidamento)

Test di promozione: questo fatto definira' ancora chi e' il personaggio o cosa
gli e' successo tra 10+ scene? Se la risposta e' no, non e' una memoria, e' un
log — resta fuori.

- Unifica eventi correlati in UNA sola voce densa, non micro-step separati.
- SI: rapporti significativi con NPC, decisioni di viaggio importanti, scontri
  con conseguenze durature, scoperte chiave.
- NO:
  - log di singoli cast (gli incantesimi vanno in spells_add, non qui)
  - riflessioni interne, tono, umore, azioni banali
  - duplicati o parafrasi di memorie gia' presenti
  - dettagli gia' coperti da un fatto piu' ampio
  - titoli politici non ancora validi in scena

ESEMPIO BUONO (una voce densa):
"Ha conosciuto [NPC]: lo ha aiutato a rifugiarsi; [dettaglio con conseguenza,
es. familiare portato via da una fazione ostile]."

ESEMPIO CATTIVO (da evitare — tre voci separate per lo stesso evento):
"Ha parlato con [NPC]." / "Ha lanciato [incantesimo]." / "Ha riflettuto sul potere."

MEMORIES_REMOVE
Togli memorie troppo granulari, duplicate o gia' assorbite in una voce piu'
ampia. Usa stringhe ESATTE da MEMORIE ATTUALI.

---

SPELLS_ADD / OPEN_THREADS / LOCATION

- spells_add: solo incantesimi nuovi, formato "Nome — descrizione breve".
  Finiscono nello spellbook del player, mai nelle memorie.

OPEN_THREADS — agenda del personaggio (wiki, persistente)

Cosa sono: impegni, obiettivi o promesse del PG non ancora conclusi — missioni
accettate, appuntamenti fissati, accordi stretti, compagni che aspettano una
risposta, indagini attivamente in corso.

Perche' possono comparire anche se gia' in situations: situations e' memoria
di SCENA (ruota o viene ripulita quando il contesto cambia); open_threads e'
l'agenda PERMANENTE del personaggio in wiki, visibile anche dopo che situations
e' stata ripulita o ha superato il limite di voci attive. Le due liste possono
contenere lo stesso filo in parallelo senza essere duplicati: sono due livelli
di memoria con scopo diverso, non la stessa lista copiata due volte.

Test di inclusione: questo filo richiede un'azione o una risposta futura del
PG? Se si', e non e' gia' presente in OPEN THREADS ATTUALI, aggiungilo. Se e'
solo uno stato di scena senza nulla da fare (es. un luogo "teso", una voce che
circola), resta in situations e basta — non diventa un'agenda item.

open_threads_add:
- Controlla SEMPRE chat e situations per fili aperti riferiti al PG prima di
  lasciare la lista invariata: non ometterli per pigrizia, ma non aggiungere
  nulla che non superi il test sopra.
- Una voce per filo, formulata come impegno concreto (chi / cosa / entro
  quando, se noto), non come cronaca dell'evento che l'ha generato.
  Esempio di formulazione: "[Azione da completare] con/per [NPC o gruppo],
  entro/scadenza [se nota]" — non "Ha parlato di [argomento] con [NPC]".

open_threads_remove: chiudi fili risolti, superati o duplicati. Usa stringhe
ESATTE da OPEN THREADS ATTUALI.

- location: aggiorna solo se il player si e' spostato stabilmente (id wiki o
  slug gia' emerso in scena).

MEMORIES — attenzione:
- NON inventare titoli, gradi o status ("cacciatore di lupi", ecc.) se non sono
  stati assegnati esplicitamente in chat. Iscriversi a una missione != ottenere un titolo.

---

SITUAZIONI RISOLTE CON SEGNO DURATURO

Se una situation chiusa ha lasciato un segno stabile su citta'/fazioni/luoghi
(non sul singolo player), promuovila in wiki tramite location_updates o
world_updates (id wiki; usa events_add / tensions_add / sections_add).

- Promuovi solo se il segno e' stabile, non rumore momentaneo.
- Non promuovere in memorie cio' che deve restare una situation aperta —
  quello e' compito della present review, non di questa.

---

CREATE_ENTITIES — nuove entita' ricorrenti emerse in chat

- Solo id semantici; type tra character|party|location|faction.
- Niente nomi inventati; niente canone assente dalla chat.

---

STATE_CLEANUP

- Stringhe ESATTE da SITUATIONS ATTUALI da rimuovere dopo la promozione
  (risolte, stale, o gia' assorbite in wiki).
- NON rimuovere fili ancora aperti e utili alle scene successive — una
  situation non promossa e non risolta resta in situations, non va qui solo
  perche' e' vecchia.
- [] se nessuna situation va rimossa.
- Non alterare campi del game_state diversi da state_cleanup e party_active.

---

Restituisci SOLO JSON valido conforme a ConsolidationReviewResult. Nessun
testo fuori dal JSON.