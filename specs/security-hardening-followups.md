# Security hardening follow-ups

The API now checks the configured application Origin for cookie-authenticated
mutations in production. Development permits a missing Origin for local scripts;
an explicitly different Origin is rejected in every environment. Browser clients
must send `Origin: <PUBLIC_APP_URL>` on POST, PUT, PATCH and DELETE.

## Tenant relationship constraints

The ingestion service rejects a workspace folder if its data source belongs to
another organization. The library projection rejects a source whose organization
differs from the requested one. These checks protect the service paths while
existing records and migration risk are assessed.

The current schema uses single-column foreign keys for tenant-bound relations.
Do not add validated composite foreign keys without a data audit. First query for
cross-organization references in `workspace_folders → data_sources`,
`processing_jobs/documents → workspace_folders`,
`document_chunks → documents`, and `library_nodes → data_sources/parent_id`.
Resolve any mismatches with an approved data repair, then create parent unique
keys and composite foreign keys using a deployment plan that accounts for table
locks and large indexes. Add database integration tests that attempt to insert
cross-tenant relationships and expect rejection.

## Retention decision pending

No TTL or purge policy was chosen for expired sessions, OAuth states, jobs,
audit records, or indexed content after source disconnection. The product owner
must define durations, deletion triggers, and backup treatment before a cleanup
job or migration is implemented.
