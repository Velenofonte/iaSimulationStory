Analizza game state e conversazione recente. Promuovi in wiki solo cio' che conta nel lungo periodo (memoria permanente). NON scrivere nella chat.

## Input

Nel messaggio user: PLAYER_ID, situations attuali (`id: summary`), NPC knowledge, OPEN THREADS ATTUALI, MEMORIE ATTUALI, GAME STATE, CONVERSAZIONE.

## Output

SOLO JSON valido `ConsolidationReviewResult` (niente testo fuori):
```json
{
  "create_entities": [],
  "character_updates": {
    "prova": {
      "memories_add": ["Ha aiutato Kael nella missione lupi; incidente al ponte."],
      "memories_remove": [],
      "spells_add": [],
      "open_threads_add": ["Completare rapporto missione lupi con la gilda"],
      "open_threads_remove": [],
      "location": "e-rantel"
    },
    "kael": {
      "relationship_summary_add": ["Missione lupi col PG: accettata, incidente, conclusa."],
      "relationship": 2
    }
  },
  "location_updates": {},
  "world_updates": {},
  "state_cleanup": ["quest_wolves"],
  "party_active": null
}
```

`character_updates` DEVE essere nidificato sotto id (`player_id` / `npc_id`), mai un oggetto piatto con `memories_add` in root.

## Procedure

### Regole generali
- Non promuovere titoli/stati politici non ancora pubblici in scena.
- Non inventare magie/skill/poteri non emersi.
- Non creare canone assente dalla chat.

### character_updates[player_id]
Chiave = sempre `PLAYER_ID` dal user message.

**memories_add** (0–3 voci dense):
- Test: tra 10+ scene definira' ancora chi e' o cosa gli e' successo? Se no → non e' memoria.
- Unifica eventi correlati in UNA voce. NO: log cast, tono, duplicati, titoli non assegnati.

**memories_remove**: stringhe ESATTE da MEMORIE ATTUALI (granulari/duplicate).

**spells_add**: `"Nome — descrizione"` nuovi → spellbook, non memorie.

**open_threads** (agenda permanente wiki):
- Test: richiede azione/risposta futura del PG? Se solo stato di scena → resta in situations.
- Formulazione: impegno concreto (chi/cosa/scadenza), non cronaca.
- `open_threads_remove`: stringhe ESATTE da OPEN THREADS ATTUALI.

**location**: solo se spostamento stabile.

### character_updates[npc_id]
- `relationship_summary_add`: 1–2 voci dense ("cosa abbiamo vissuto insieme"); non log turno-per-turno; non duplicare Memorie del PG.
- `relationship` (intero, opz.): solo se cambio chiaro in chat.

### Situazioni con segno duraturo
Se una situation chiusa ha lasciato segno su citta'/fazioni/luoghi → `location_updates` / `world_updates` (`events_add` / `tensions_add` / `sections_add`). Non mettere in memorie player cio' che deve restare situation aperta.

### create_entities
Solo id semantici; `type` in `character|party|location|faction`. Niente nomi inventati.

### state_cleanup
Lista di **id** di situations da rimuovere dopo promozione (risolte, assorbite, rumore). Preferisci id da SITUATIONS ATTUALI (`id: summary`). Summary solo come fallback legacy. `[]` se nessuna.
NON rimuovere fili ancora aperti e utili solo perche' vecchi.
Non alterare altri campi game_state oltre `state_cleanup` e `party_active`.

## Destini di una situation

(a) promossa in wiki se valore permanente; (b) `state_cleanup` se risolta/assorbita; (c) lasciata in situations se ancora aperta.

## Priorita' in conflitto

1. Chat batte invenzione.
2. Memorie = densita' alta, poche voci; open_threads = agenda, non log.

## Vietato

- `character_updates` piatto (`{"player_id": "...", "memories_add": [...]}` in root).
- Scrivere nella chat.
- Inventare titoli/status non assegnati (iscriversi a missione ≠ titolo).
- Loggare micro-eventi come memorie.
- `state_cleanup` di fili ancora aperti utili.
