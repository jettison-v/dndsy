# Artifacts: the source of every page published on claude.ai

Pages Claude publishes for askdnd (plans, explorations, before-and-after comparisons) are hosted on claude.ai, private
to Brett's account. This folder keeps their source in git, so they outlive any one Claude account or session: GitHub
and every clone hold a copy, and any page can be opened in a browser or published again from here.

**The rule** (CLAUDE.md): a page published for askdnd has its source in the repo. Pages that are kept up to date
live where they belong (`docs/stack.html`, `docs/mockups/`); this folder holds the rest, saved when they're published.
Treat the repo as public (it's private for now, and may open again), so nothing goes here that couldn't be: no book text, campaign story or players' notes, and no
screenshots of real pages (they show the campaign).

| Page | Link on claude.ai | Here | What it was |
|---|---|---|---|
| askdnd Manage Menu | [Y3ZKdQHFykyR9ywm3sV7at](https://claude.ai/artifact/Y3ZKdQHFykyR9ywm3sV7at) | `../mockups/manage-menu.html` | A six-item Manage menu, a section list down the left of Manage pages, an askdnd admin Overview, names in order (approved, Oct 27); round 2: three ways to tell this campaign from askdnd admin |
| askdnd Data Strategy | [PWXtaunHcp3MEEJyJpLWoe](https://claude.ai/artifact/PWXtaunHcp3MEEJyJpLWoe) | `data-strategy.html` | Where askdnd's data lives: four buckets, books checked once (decided, Oct 27); the record is `../plans/2026-10-27-data-strategy.md` |
| askdnd Stack Map | [AYYGdebsBtPND4HoTq5uyr](https://claude.ai/artifact/AYYGdebsBtPND4HoTq5uyr) | `../stack.html` | How the services connect, who changes each, where the data lives (kept current) |
| Battle Slim Header | [CXkXguKnGmrPMnPXDYjwP2](https://claude.ai/artifact/CXkXguKnGmrPMnPXDYjwP2) | `../mockups/battle-header.html` | Battle's header shrinking to one row as you scroll (Oct 27). Not built: Brett chose to let the header scroll with the page |
| askdnd D&D Beyond Bridge | [9H59RDNi99gVa7bNwmjp6G](https://claude.ai/artifact/9H59RDNi99gVa7bNwmjp6G) | `ddb-bridge.html` | How the bridge proof works and repairs itself, and the real run on Vi (Oct 27) |
| Party Redesign | [EJmFmzbXoV15HKjpJiJ18a](https://claude.ai/artifact/EJmFmzbXoV15HKjpJiJ18a) | `../mockups/party.html` | The Party page built from the rest of askdnd's pieces (proposal, Oct 26) |
| askdnd VTT Roadmap | [EtCBFsKNwLK5LNhQjcbzS3](https://claude.ai/artifact/EtCBFsKNwLK5LNhQjcbzS3) | `vtt-roadmap.html` | The roadmap, fight screen first (Oct 27); the record is `../plans/2026-10-22-vtt-roadmap.md` |
| askdnd content workflows | [MPiEDh3KMNmB2NoCtuq52U](https://claude.ai/artifact/MPiEDh3KMNmB2NoCtuq52U) | `content-workflows.html` | Recaps, entries and suggestions, start to finish (Oct 22) |
| askdnd campaigns and roles | [LLRsdZLY7wf5W7vTp4SEZR](https://claude.ai/artifact/LLRsdZLY7wf5W7vTp4SEZR) | `campaigns-and-roles.html` | Data organization: campaigns, roles per campaign (Oct 22) |
| askdnd design system | [TJBLGJti8JCkUfN2BXph8K](https://claude.ai/artifact/TJBLGJti8JCkUfN2BXph8K) | `design-system-plan.html` | The design system plan and Brett's answers (Oct 22); the living version is Manage › Design system |
| askdnd step 3 before and after | [8wDE5Mes9sjAqUbfmosakD](https://claude.ai/artifact/8wDE5Mes9sjAqUbfmosakD) | `step-3-before-after.html` | Character pages on the design system (screenshots stay on claude.ai) |
| askdnd step 4 before and after | [PqQRvc1cyx52vWrsdUKwDQ](https://claude.ai/artifact/PqQRvc1cyx52vWrsdUKwDQ) | `step-4-before-after.html` | Story and Manage pages on the design system (screenshots stay on claude.ai) |
| askdnd lists: open questions | [SkZpGVy97JqLcxyi3zyUE4](https://claude.ai/artifact/SkZpGVy97JqLcxyi3zyUE4) | `lists-open-questions.html` | Questions answered before the list pattern was built (Oct 21) |
| askdnd lists and filters | [DsaXefMSwqfssr9Nr9CX6G](https://claude.ai/artifact/DsaXefMSwqfssr9Nr9CX6G) | `lists-and-filters/` | One list-and-filter pattern everywhere (a design canvas) |
| askdnd spellcasting ideas | [MugmGvRMCLnPotQWf2fzFc](https://claude.ai/artifact/MugmGvRMCLnPotQWf2fzFc) | `spellcasting-ideas/` | The Spell Book explorations (a design canvas) |
| askdnd table rolls ideas | [4hB75v84hYmrJwYUoTADfr](https://claude.ai/artifact/4hB75v84hYmrJwYUoTADfr) | `table-rolls-ideas/` | Table rolls explorations (a design canvas) |
| askdnd navigation ideas | [4NJKfKE7uyTEKu6y4vVgn2](https://claude.ai/artifact/4NJKfKE7uyTEKu6y4vVgn2) | `navigation-ideas/` | Menu bar and character page explorations (a design canvas) |

The design canvases are folders: one `.dc.html` file per board and `canvas.json` for their titles and layout. Each
board is plain HTML with inline styles; it opens in a browser without the canvas around it.
