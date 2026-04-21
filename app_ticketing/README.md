# Agent Ticketing System Setup

This directory contains the ticketing service for the CloudOps Agents project.
The agent fetches infrastructure requests from a BigQuery table and processes them.

## BigQuery Setup

The agent expects a BigQuery table to store and retrieve tickets. Follow these steps to set it up.

### 1. Create Dataset

Use the `bq` command-line tool to create a dataset. Replace `<PROJECT_ID>` and `<DATASET_NAME>` with your values.

```bash
bq mk --dataset_id=<PROJECT_ID>:<DATASET_NAME>
```

### 2. Create Table

You can create the table using SQL or the `bq` CLI.

#### Option A: SQL Creation (Recommended)

Run this SQL query in the BigQuery console or using `bq query`:

```sql
CREATE TABLE `<PROJECT_ID>.<DATASET_NAME>.tickets` (
  ticket_id STRING,
  project_id STRING,
  requester STRING,
  type STRING,
  status STRING,
  description STRING,
  payload JSON,
  recommendation STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Option B: CLI Creation

```bash
bq mk --table <PROJECT_ID>:<DATASET_NAME>.tickets \
  ticket_id:STRING,project_id:STRING,requester:STRING,type:STRING,status:STRING,description:STRING,payload:JSON,recommendation:STRING,created_at:TIMESTAMP
```

### 3. Permissions

Ensure the service account used by the agent has the following roles:
- `roles/bigquery.dataEditor` on the dataset.
- `roles/bigquery.jobUser` on the project.

## Simulating a Ticket

To simulate a new ticket for the agent to process, you can insert a row into the table:

```sql
INSERT INTO `<PROJECT_ID>.<DATASET_NAME>.tickets` (ticket_id, project_id, requester, type, status, description, payload)
VALUES (
  'TICKET-001',
  '<TARGET_PROJECT_ID>',
  'user@example.com',
  'connectivity_check',
  'pending',
  'Check connectivity from source to destination',
  JSON '{"source": "10.0.0.1", "destination": "10.0.0.2"}'
);
```
