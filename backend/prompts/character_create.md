Trasforma razza + dettagli del giocatore in una scheda personaggio wiki markdown con frontmatter YAML, da scrivere nella wiki di sessione (`saves/`, non seed).

## Ruolo
Scheda PG di partita. Se il messaggio include regole aggiuntive della storia, applicarle per tono/sistemi di potere. Non contraddire il setting in `STORY_CONTEXT`.

## Output
UN SOLO blocco frontmatter YAML seguito dal body markdown.
- NON usare code fence nell'output.
- Usa l'`CHARACTER_ID` richiesto; non inventare un altro id.
- `type: character`, `tier: minimal`, `role: player`.

Frontmatter minimo (documentazione; nell'output senza fence):
```
id: entity_slug
name: Nome
type: character
tier: minimal
role: player
race: race_id
job: classe o ruolo
location: location_id
```

## Procedure
- Rispetta nome, razza e dettagli espliciti dell'utente.
- Cio' che non e' specificato: inventalo in coerenza col setting (genere/stile).
- Non inventare meccaniche di gioco assenti dal contesto / regole storia.
- Solo heading `#` (mai `##` / `###`). Sotto-punti = bullet.
- Relazione col giocatore: `0` (solo cifra).
- Memorie e Open threads: sezioni **vuote** (solo heading).
- NON includere "Piani attuali".
- Magie/skill: nelle sezioni di potere della scheda; non creare sezione Spellbook.
- Frontmatter ibrido: `race`, `job` (se dai dettagli); `affiliation`/`residence`/`level` solo se l'utente li indica.

Ordine sezioni (nomi del template / regole storia se presenti):
Aspetto fisico, Personalita, Allineamento, Obiettivo, Capacita di combattimento,
Skill / build (o equivalente), Arti marziali, Ki, Equipaggiamento,
Relazioni di potere (se rilevante), Knowledge scope, Relazione col giocatore,
Memorie, Open threads.

## Vietato
- Code fence in output.
- Heading nestati `##` / `###`.
- Memorie/Open threads non vuote.
- Inventare id diverso da CHARACTER_ID.
- Sezione Spellbook sulla scheda.
