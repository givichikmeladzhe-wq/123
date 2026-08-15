# AI OS Notion implementation package

This repository contains a deployment package for the **Notion operational
state only**, transcribed from section 9 of
`AI_OS_Control_Operational_State_Memory_Audit_TZ_v1.1.html`.

Nothing in this package contacts Notion unless both `--execute` and the
required environment variables are supplied. Start with:

```bash
python3 scripts/deploy_notion.py plan --output build/notion-plan.json
python3 -m unittest discover -s tests -v
```

See [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) for the creation order,
manual view/template runbook, API limitations, and deployment instructions.
