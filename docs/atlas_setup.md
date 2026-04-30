# MongoDB Atlas setup

Current Atlas setup:

```text
Organization: SmartStudy H505
Project: smartstudy-h505
Cluster: smartstudy-h505
Database: smartstudy
Collection: lecture_chunks
Vector index: lecture_vector_index
```

The vector index is created on `smartstudy.lecture_chunks`.

Indexed fields:

- `embedding` as the vector field
- `source_file` as a filter field
- `page` as a filter field

The connection string is a secret. Keep it in a local `.env` file during development and in Google Secret Manager for deployed code. Do not commit it to GitHub.

## Team access

Invite teammates to the Atlas organization/project with their own accounts. Do not share a personal login.

Database network access is separate from project membership. Add a teammate's IP only if they need to connect from their own machine.

## Current status

- Database and collection created.
- Vector index created.
- Index may show `PENDING` until Atlas finishes building it. With an empty collection, `0 documents indexed` is expected.

