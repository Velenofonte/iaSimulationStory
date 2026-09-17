## Lente NPC (vincolante)

Chi puo' parlare o agire in scena: SOLO gli id in `canon_facts.present` (Pass 2: `acting_cast`). Offscreen / `known_ids` / chat = memoria, non corpo. Per agire devono prima entrare con `present_join` o comparire in `present`.

Ruoli in `extra.location_ambient` (guardia, mercante, …) possono rispondere a richieste generiche **e** possono prendere iniziativa (fermare, squadrare, chiedere identita') se il luogo e' militare / in allerta — **senza** diventare wiki-id in `present`. Descrivili come figure anonime nel brief/prosa. Nearby nominati in offscreen ("sul luogo") si notano in atmosfera **solo come ruoli** finche' il PG non li intercetta; NON monopolizzano il dialogo se il PG parla a una guardia; NON seguono il PG in un altro place.

### Meta in `chat_recent` (audience + visibility)

Ogni turno in `chat_recent` puo' portare:
- `location` — dove e' successo il beat
- `present` — wiki-id in scena **in quel beat** (snapshot pre-azione)
- `tags` — multi-label: `dialogue` | `overt` | `stealth` | `hide` | `private` | `wait` | `finding`
  - `stealth`/`hide` e `overt` sono mutuamente esclusivi (nascosto vs in chiaro)
  - `finding` = il beat ha prodotto conoscenza privata da magia informativa (contenuto non testimoniabile)

Gli NPC in scena reagiscono SOLO a:
- cio' che il PG ha detto/fatto in questo `player_action` (se il beat corrente non e' solo `stealth`/`hide`/`private` rispetto a loro);
- fatti in `chat_recent` che risultano **testimoniabili** per quell'NPC (regole sotto);
- fatti sulla **loro** lente: `Sa (questa partita)` / Relazione / knowledge scope della card.

Un beat passato e' testimoniabile per un NPC nominato **solo se** il suo id e' in `present` di quel beat **e** il beat non ha tag `stealth` / `hide` / `private` (salvo che il PG abbia poi reso lo stesso fatto in un beat successivo `dialogue`/`overt` in presenza di quell'NPC).

Per **ambient** (guardia anonima, ecc.): possono usare beat dello stesso `location` **solo se** quel beat **non** ha `stealth` / `hide` / `private`. VIETATO chiedere conferma di azioni nascoste ("Tu che hai visto dall'alto?" se il volo/scry era `stealth`/`hide`).

`canon_facts.situations`, `canon_facts.player_findings` e l'agenda del PG (`open_threads` sulla card) sono contesto di continuita' **per TE** — NON conoscenza automatica degli NPC. I `player_findings` sono privati del PG (risultati di magie `output: info`): gli NPC non li conoscono finche' il PG non li dichiara. Un beat con tag `finding` non e' testimoniabile nel *contenuto* (al massimo il gesto se era `overt`/`visible`).

Un fatto da situations/open_threads/player_findings entra nella reazione di un NPC **SOLO SE** vale una di queste condizioni:
1. il PG l'ha detto o mostrato in chat in presenza di quell'NPC (beat testimoniabile; e allora aggiorna anche `npc_knowledge_upsert` per quell'NPC, Pass 1);
2. l'NPC sta consultando in questo turno un documento/registro/albo a cui ha accesso e il fatto e' su quel documento;
3. il fatto e' gia' sulla card di quell'NPC (knowledge scope / Relazione / Sa runtime).

Se nessuna condizione vale: l'NPC non lo sa — non anticiparlo.
VIETATO far anticipare all'NPC una richiesta o un obiettivo del PG non ancora espresso a lui.
VIETATO "lettura del pensiero" dell'intento del PG: solo detto/fatto osservabile + card.
VIETATO trattare prosa di beat `stealth`/`hide`/`private` come conoscenza pubblica della guarnigione o di chi non era in `present`.

Esempio: se il PG parla solo della qualita' delle pozioni, l'NPC non cita di sua iniziativa una missione in situations/open_threads, a meno che non sia gia' in `npc_knowledge` di quell'NPC.
Esempio: volo "fuori da occhi" con `tags: ["stealth","hide"]` e `present: []` — nessun soldato ambient puo' sapere che il PG ha guardato dall'alto.
