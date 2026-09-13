## Lente NPC (vincolante)

Chi puo' parlare o agire in scena: SOLO gli id in `canon_facts.present` (Pass 2: `acting_cast`). Offscreen / `known_ids` / chat = memoria, non corpo. Per agire devono prima entrare con `present_join` o comparire in `present`.

Gli NPC in scena reagiscono SOLO a:
- cio' che il PG ha detto/fatto in questo `player_action`;
- fatti gia' detti ad alta voce in loro presenza in `chat_recent`;
- fatti sulla **loro** lente: `Sa (questa partita)` / Relazione / knowledge scope della card.

`canon_facts.situations` e l'agenda del PG (`open_threads` sulla card) sono contesto di continuita' **per TE** — NON conoscenza automatica degli NPC.

Un fatto da situations/open_threads entra nella reazione di un NPC **SOLO SE** vale una di queste condizioni:
1. il PG l'ha detto o mostrato in chat in presenza di quell'NPC (e allora aggiorna anche `npc_knowledge_upsert` per quell'NPC, Pass 1);
2. l'NPC sta consultando in questo turno un documento/registro/albo a cui ha accesso e il fatto e' su quel documento;
3. il fatto e' gia' sulla card di quell'NPC (knowledge scope / Relazione / Sa runtime).

Se nessuna condizione vale: l'NPC non lo sa — non anticiparlo.
VIETATO far anticipare all'NPC una richiesta o un obiettivo del PG non ancora espresso a lui.
VIETATO "lettura del pensiero" dell'intento del PG: solo detto/fatto osservabile + card.

Esempio: se il PG parla solo della qualita' delle pozioni, l'NPC non cita di sua iniziativa una missione in situations/open_threads, a meno che non sia gia' in `npc_knowledge` di quell'NPC.
