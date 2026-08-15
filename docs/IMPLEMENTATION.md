# Notion operational-state deployment runbook

## Scope and source

This package implements only section 9 of the supplied TZ. It does not
implement Hermes, adapters, SQLite/WAL, queues, leases, reconciliation, audit
writing, Obsidian automation, replay, Telegram, runners, RAG, transcript
processing, or any production automation. Long-form content belongs in page
bodies and secrets must never be stored in these data sources.

The canonical machine-readable specification is
`schema/notion_schema.json`. It contains all 11 data sources, the common
properties, entity-specific properties, exact enumerated values, relations,
requested views, and minimal template outlines. Empty option lists are
intentional: the TZ does not enumerate values for `Agents.Role`,
`Source Events.Sensitivity`, or the dynamic `Changes.Changed Fields`.

## Creation order

1. Create an `AI Operating System` parent page and share it with the Notion
   integration.
2. **Phase 1:** create the 11 databases/data sources in this order: Projects,
   Tasks / Backlog, Decisions, Open Questions, Agents, Agent Brain / Prompt
   Versions, Operating Manual, Changes, Source Events, Approvals, Briefings.
   Create every non-relation property at this stage.
3. Record both the database ID and its first data-source ID from every API
   response.
4. **Phase 2:** patch all relation properties, now resolving their target by
   data-source ID. Self-relations are safe because every source already exists.
5. **Phase 3:** create the views from the table below in the Notion UI.
6. **Phase 4:** create the seven minimal templates from the schema file.
7. Validate manually using `TEST` pages, then delete or retain them with the
   `TEST` prefix: Project → Task/Decision/Question/Agent/Briefing; Task →
   Decision/Source Event; Agent → Brain Version; Manual → Decision; Briefing →
   Project/Tasks/Decisions/Questions.

The script implements phases 1–2 only. It emits phases 3–4 into its offline
plan so the manual work is explicit and reviewable.

## Views

All views are table views unless the operator deliberately chooses another
layout. `By …` views group on the named relation/select; recent views sort
descending; all other views filter as follows.

| Database | View | Filter / grouping / sort |
|---|---|---|
| Projects | Active Projects | Status = ACTIVE |
| Projects | All Projects | no filter |
| Projects | On Hold | Status = ON_HOLD |
| Projects | Operating | Status = OPERATING |
| Tasks / Backlog | Inbox | Status = INBOX |
| Tasks / Backlog | Backlog | Status = DRAFT |
| Tasks / Backlog | Ready | Status = READY |
| Tasks / Backlog | In Progress | Status = IN_PROGRESS |
| Tasks / Backlog | Blocked | Status = BLOCKED |
| Tasks / Backlog | Awaiting Approval | Status = AWAITING_APPROVAL |
| Tasks / Backlog | Done | Status = DONE |
| Tasks / Backlog | By Project | group by Project |
| Decisions | Needs Review / Awaiting Approval / Approved / Superseded | Status equals the corresponding uppercase value |
| Decisions | By Project | group by Project |
| Open Questions | Open | Status = OPEN |
| Open Questions | Needs Андрей | Status = NEEDS_ANDREY |
| Open Questions | Blocking | Impact = BLOCKING and Status is not ANSWERED/DROPPED |
| Open Questions | By Project | group by Project |
| Agents | Active / Proposed / Paused | Status equals the corresponding uppercase value |
| Agents | By Project | group by Projects |
| Agent Brain / Prompt Versions | Draft / Proposed | Status is DRAFT or PROPOSED |
| Agent Brain / Prompt Versions | Evaluating / Awaiting Approval / Active | Status equals the corresponding uppercase value |
| Agent Brain / Prompt Versions | Version History | no filter; group by Agent, sort Version descending |
| Agent Brain / Prompt Versions | By Agent | group by Agent |
| Operating Manual | Active | Status = ACTIVE |
| Operating Manual | Draft / Review | Status is DRAFT or REVIEW |
| Operating Manual | By Scope / By Project / By Agent | group by Scope / Projects / Agents |
| Changes | Recent Changes | sort Occurred At descending |
| Changes | Unreconciled | Status = UNRECONCILED |
| Changes | Audit Pending | Status = AUDIT_PENDING |
| Changes | By Entity | group by Entity Type, then sort Entity ID |
| Source Events | Recent Sources | sort Occurred At descending |
| Source Events | Raw Transcripts / Operational Packages | Type = RAW_TRANSCRIPT / OPERATIONAL_PACKAGE |
| Source Events | By Project | group by Projects |
| Source Events | Failed / Quarantined | Processing Status is FAILED or QUARANTINED |
| Approvals | Pending / Approved | Status = PENDING / APPROVED |
| Approvals | Rejected / Expired | Status is REJECTED or EXPIRED |
| Approvals | By Type | group by Type |
| Briefings | Today | Scheduled At is today |
| Briefings | Scheduled / Processing / Closed | Status equals the corresponding uppercase value |
| Briefings | Failed / Skipped | Status is FAILED or SKIPPED |
| Briefings | By Project | group by Project |

## Safe commands

Generate inspectable API requests without network access:

```bash
python3 scripts/deploy_notion.py plan --output build/notion-plan.json
```

Deployment is guarded and is **not** run as part of this package:

```bash
export NOTION_TOKEN='secret_...'
export NOTION_PARENT_PAGE_ID='...'
python3 scripts/deploy_notion.py apply --execute
```

Requests use data sources and `Notion-Version: 2026-03-11`, as required by the
TZ. Re-running `apply` is not idempotent: it creates a new set of databases.
Always review the generated plan and deploy once into an empty parent page.

## Notion/API limitations and minimal treatment

1. **Views:** the public API used by the script does not provide a supported
   endpoint for configuring database views, filters, sorts, or groups.
   Therefore views are a documented manual phase. This does not affect
   properties or relations, but the workspace is not operationally convenient
   until phase 3 is completed.
2. **Database templates:** the API does not provide a general endpoint to
   create/edit data-source templates. Seven useful templates are specified for
   manual creation. Existing templates can be used when creating pages, but
   that is different from defining them.
3. **Required, immutable, defaults, and cardinality:** Notion schema metadata
   cannot enforce `required`, immutable Entity IDs, `State Version = 0`,
   `Briefing Enabled = true`, exactly-one relations, acyclic task dependencies,
   or status-dependent requirements. The schema records these rules; operators
   must follow them until a future adapter exists. No backend is added here.
4. **Two title fields:** common properties require `Name` as `title`, while the
   Operating Manual row also describes `Topic` as `title`. Notion permits one
   title property per data source. Minimal treatment: `Name` remains the title
   and `Topic` is `rich_text`. No other database is affected.
5. **Unspecified enumerations:** the TZ names `Role`, `Sensitivity`, and
   `Changed Fields` types but supplies no allowed values. The package creates
   those property types without inventing options; values are added only when
   authoritative policy defines them.
6. **Status schema support:** if the pinned API version rejects creation or
   option configuration for a `status` property, create that single property
   and its listed options manually with exactly the names in the schema. Do not
   silently substitute `select`; relations and all other databases are
   unaffected.
7. **Relation duplication:** the package creates explicit single-direction
   relation properties named by the TZ, rather than relying on Notion-generated
   reciprocal names. This avoids collisions (especially two Briefing → Source
   Events fields) and preserves every required navigation field.

## Acceptance checklist

- [ ] Exactly 11 databases exist under the chosen parent.
- [ ] Every database has `Name`, stable `Entity ID`, `State Version`, source and
      change traceability, audit marker, and Notion system timestamps/users.
- [ ] All exact status/select/multi-select values in the JSON are present.
- [ ] Every relation target opens and accepts a linked page.
- [ ] All requested views and seven templates are created manually.
- [ ] Relation smoke test described in step 7 passes.
- [ ] No non-TEST fictional content or secrets were inserted.
