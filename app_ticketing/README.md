# Agent Ticketing

This directory contains the agent for processing infrastructure tickets.

## Database Setup

The agent expects a BigQuery table to store tickets.

### 1. Create Dataset

Use the `bq` command-line tool (included in the Google Cloud SDK) to create a dataset:

```bash
bq mk --dataset_id=<PROJECT_ID>:<DATASET_NAME>
```

Example:
```bash
bq mk --dataset_id=my-project-id:agent_ticketing
```

### 2. Create Table

#### Option A: Using SQL (Recommended)

Run the following SQL query in the BigQuery console or via `bq query`:

```sql
CREATE TABLE `<PROJECT_ID>.<DATASET_NAME>.tickets` (
  ticket_id STRING,
  project_id STRING,
  requester STRING,
  type STRING,
  status STRING,
  description STRING,
  payload JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Option B: Using `bq` CLI

```bash
bq mk --table <PROJECT_ID>:<DATASET_NAME>.tickets \
  ticket_id:STRING,project_id:STRING,requester:STRING,type:STRING,status:STRING,description:STRING,payload:JSON,created_at:TIMESTAMP
```

Note: The SQL option is recommended as it allows setting the default value for `created_at`.

## Configuration

If you use a specific dataset name (e.g., `agent_ticketing`), you may need to update the query in `app_ticketing/ticketing/tools.py` to reference it:

```python
        FROM `<PROJECT_ID>.<DATASET_NAME>.tickets`
```

Currently, it assumes the table `tickets` is in the default dataset.
