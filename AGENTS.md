# AGENTS.md — Wiki Overlord

## Layer
- `raw/` sorgenti immutabili dal web
- `stories/<story_id>/wiki/` seed canone (ingest aggiorna qui; runtime non scrive)
- `stories/<story_id>/wiki/fronts/` archi narrativi (YAML beat) **specifici dell'ambientazione**
- `stories/<story_id>/wiki/overlays/<arc_id>/` titoli/epoca legati all'arco
- `stories/<story_id>/meta.yaml` meta storia (`genre`, `narrative_style`, start, default_front)
- `stories/<story_id>/prompts/` regole ingest/tono/episodi opzionali del pack (non nel motore generico)
- `stories/<story_id>/events.yaml` pesi e bande del motore episodi/notorieta (pack ambientazione)
- `saves/<session_id>/wiki/` clone privato della partita (schede, world, spellbook)
- `saves/<session_id>/` stato partita + chat (non toccare con ingest)

I prompt in `backend/prompts/` sono del **motore** (comportamento turno/review); non contengono lore di setting.

## Convenzioni pagina
Frontmatter personaggio (ibrido):
```yaml
id: entity_id
name: Nome
type: character
tier: minimal|growing|canonical
source: url o seed
race: razza lore          # se documentata
job: ruolo / classi       # oppure classes: [...]
affiliation: nazione/gilda/fazione  # [[id]] se esiste
residence: luogo tipico   # se canonico
level: 100                # SOLO se esplicito in sorgente
```

Altri tipi: `location|faction|party|world|nation` con frontmatter minimo `id`, `name`, `type`, `tier`, `source`.

### Scheda **base** (invarianti) — solo heading `#`, mai `##` / `###`
Ordine sezioni:
1. Aspetto fisico
2. Personalita
3. Allineamento
4. Obiettivo — solo obiettivo stabile (non piani d'epoca)
5. Capacita di combattimento — riassunto tattico; **solo testo/bullet**
6. Skill / build YGGDRASIL — sezione H1 dedicata (o `Nessuna`)
7. Arti marziali / Ki — sistemi separati
8. Equipaggiamento
9. Relazioni di potere
10. Knowledge scope (sa / non sa)
11. Relazione col giocatore (`0` in seed)
12. Memorie / Open threads — **sempre vuote in seed** (runtime sessione)
13. Notorieta — **sempre vuota in seed** (runtime sessione: etichette, portata, imprese note al mondo)

**NON** sulla base: Piani attuali, titoli/stato politico d'epoca, Open threads pieni, Notorieta piena.
**NON** nestare heading: vietato `## Skill / build` dentro Capacita — usare `# Skill / build YGGDRASIL` o bullet.

Magie dettagliate → `wiki/spellbooks/<id>.md` (non lista completa sulla scheda).

### Overlay per arco (`wiki/overlays/<arc_id>/characters/`)
Frontmatter: `id`, `arc`, `extends`, opz. `role`/`name` epoca.
Sezioni tipiche (sostituiscono omonime della base):
- Titoli validi / Stato nell'arco
- Obiettivi / Piani attuali legati all'epoca
- Knowledge scope ristretto all'arco
**NON** mettere in overlay: magie, skill YGGDRASIL, arti marziali, Ki, rapporti di potere assoluti, aspetto/personalita invarianti.

Link: `[[entity_id]]`

## Ingest
1. Priorita' light novel > anime
2. Personaggi canonici -> tier canonical + knowledge scope esplicito + frontmatter ibrido
3. Scrivere SOLO nella seed `stories/<story_id>/wiki/` (default: overlord)
4. Non toccare `saves/*/wiki` (memorie/open threads di partita)
5. Aggiornare index.md ad ogni nuova entita'
6. Poteri invarianti sulla scheda base; titoli/epoca in `overlays/<arc>/`; spellbook separato
7. Post-process: flatten heading nestati (`##` → H1 o bullet)

## Query
- mode scene: location + presenti + entita' nominate
- mode character: solo scheda NPC + knowledge scope

## Lint
- link [[id]] devono risolvere
- party members devono esistere
- body personaggio senza heading `##` / `###`
