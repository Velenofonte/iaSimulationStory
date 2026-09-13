## Grammatica player_action (vincolante)

Marker nel messaggio del PG, in **sequenza letterale** (non riordinare):

| Marker | Significato | Regola |
|---|---|---|
| `"..."` / `«...»` | parole dette ad alta voce | fatto obbligatorio: il PG ha parlato (interlocutore/topic). VIETATO omettere |
| `[...]` | magia / cast | `[Nome — descrizione]` nuovo → `spells[]`; `[Nome]` solo nome → non inventare description. Bullet/effetto con **scala** da spellbook + world_pages (magic-tier). Se la potenza implica devastazione (paesaggio, citta', armate): scrivila esplicita — VIETATO soft-pedalare a "scintilla" / effetto locale innocuo |
| `*...*` | pensiero interno | non udito dagli NPC. Al massimo un fatto se cambia intenzione rilevante; non trattarlo come dialogo |
| testo libero | azione fisica/scena | narrata / messa nel brief normalmente |

Esempio: `"Mi fido." *spero non mi uccida* [Sigillo] e abbasso la barriera`
→ ordine: detto fiducia → (opz. pensiero) → cast → abbassa barriera.

Se un evento front interrompe: marca l'interruzione dopo i passi gia' avviati; non cancellare in silenzio le `"..."` gia' in `player_action`.
