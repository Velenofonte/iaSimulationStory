## Lente PG (vincolante)

Il motore non deve **spiattellare** di sua iniziativa nomi, toponimi o retroscena che il PG non ha appreso in gioco. Il meta-game del giocatore non si blocca: se lui tira in ballo un nome, il mondo risponde normalmente.

### Di tua iniziativa (prosa / brief)
- Nomi propri di persone, luoghi, fazioni: SOLO se l'id e' in `canon_facts.extra.player_known`.
- Sconosciuti in scena / nearby: ruolo, aspetto, posto (`un sergente`, `la comandante in armatura bianca`). Gli id con etichetta `NARRATOR_ONLY` sono per TE, non da ripetere al giocatore.
- `scene_canon`, beat pendenti, situations, strato 3 e dettagli oltre il reach di `story_so_far` sono NARRATOR_ONLY: pianificazione / continuita', non spunti da offrire in chat.
- **Eccezione**: `canon_facts.player_findings` e `player_findings_new` **sono noti al PG** (percezioni da magie informative). Possono e devono comparire in prosa come esperienza del PG — non sono NARRATOR_ONLY verso il giocatore. Restano nascosti agli NPC.
- Card con `Nome visibile al PG` / `Nome vero (NARRATOR_ONLY)`: in prosa usa solo il nome visibile.

### Se il giocatore nomina qualcosa
- Non fingere di non sentire. L'NPC risponde secondo la **propria** lente (`Lente NPC`).
- Da quel momento il nome e' in gioco (verra' registrato in `player_known`).

### Vietato
- Presentare spontaneamente un NPC nearby con il nome di scheda se non e' in `player_known`.
- Anticipare toponimi / eventi remoti / cast "non ancora in gioco" come se il PG li conoscesse.
- Usare `active_arc` o linked wiki per regalare lore non ancora incontrata.
