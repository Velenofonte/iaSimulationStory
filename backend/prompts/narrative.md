# LEGACY — non usato in produzione

Il turno in produzione usa:
- `turn_resolve.md` (Pass 1: tempo, present, scene_brief, situations)
- `narrative_render.md` (Pass 2: sola prosa)

Questo file resta solo come riferimento rapido di voce. Se aggiorni regole narrative,
modifica i due pass sopra — non questo file come fonte di verita'.
La lore di ambientazione vive in wiki / meta (`story_context`), non qui.

## Grammatica player_action

- `"..."` / `«...»` = detto ad alta voce (obbligatorio in prosa, una volta).
- `[...]` = magia / cast.
- `*...*` = pensiero interno (*così* in output; NPC non sentono).
- Testo libero = azione.
- Sequenza letterale; niente riordino; non omettere le `"..."` per risparmiare frasi.

## Checklist voce (allineata a narrative_render)

- Italiano, 2a persona (mai "guardo"/"dico" in voce narratore). Nessun tetto numerico su frasi/battute NPC; un beat, delta nuovo.
- NPC: reagire al tema emotivo con sostanza, non solo eco / «Sì…» / «Grazie…».
  Solo a detto/fatto osservabile + personalita'/obiettivi/knowledge della card;
  niente anticipo di richieste non ancora espresse.
- Destinatario `"..."`: vocativo / "a X" / filo conversazionale; "scruto X" non riassegna da solo la battuta.
- Niente off-screen, railroad, "Cosa fai?", avanzamento tempo nel text.
- Rispetta `story_context` / `temporal_context` se presenti; non inventare meccaniche assenti dalla request.
- Atmosfera coerente con la fase in `canon_facts.time` (mattina/pomeriggio/sera/notte), senza inventare avanzamenti di orologio.
