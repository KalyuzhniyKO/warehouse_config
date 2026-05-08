# TODO: business audit logging

`AuditLog` is not implemented yet. Add a database-backed business audit log before relying on filesystem logs for accountability or compliance.

## Future events to store in the database

The future audit log should record at least:

- login/logout;
- створення номенклатури;
- зміна номенклатури;
- архівування;
- initial_balance;
- приход;
- видача;
- повернення;
- списання;
- переміщення;
- інвентаризація;
- друк етикетки;
- імпорт;
- експорт;
- зміна налаштувань.

## Suggested fields

- event timestamp;
- user id and username;
- event type;
- object type and object id;
- before/after values for changes where practical;
- request id or correlation id;
- source IP/user agent for web actions;
- human-readable message.

## Implementation notes

- Keep audit records append-only.
- Restrict delete/update permissions for audit records.
- Add admin filters by user, event type, object, and date range.
- Include export tooling for investigations.
