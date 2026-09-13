## Registro ID (vincolante)

`canon_facts.known_ids` (o le liste runtime nella review) elenca gli id gia' assegnati:
- `known_ids.situations`: fili medi `[{id, summary}]`
- `known_ids.npc_knowledge`: `{npc_id: [{id, summary}, ...]}` (anche NPC fuori scena)
Sulle character_cards, la riga `Sa (questa partita)` mostra `id: summary`.

Regole:
1. **Stesso filo/evento** → RIUSA l'id esistente e aggiorna solo `summary`.
2. **Nuovo filo** → slug corto stabile (`reclamo_kael`, `foresta_signore`); VIETATO varianti (`reclamo_kael_mattina`, `reclamo_kael_v2`).
3. Fasi distinte sullo stesso filo solo se servono DUE record contemporanei: suffissi `_start` / `_done` (raro).
4. `situations_remove` / chiusura fili: lista di **id** (non il testo `summary`).
5. VIETATO ripetere un fatto gia' presente con un id diverso.
6. Se incerto su `npc_knowledge_upsert`: lascia `{}` (fail-closed). MAI includere il PG. MAI copiare situations globali su tutti i presenti.
