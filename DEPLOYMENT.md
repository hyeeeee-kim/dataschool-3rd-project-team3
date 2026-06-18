# Databricks Apps Deployment Guide

## Deployment target

- Source type: Workspace folder
- Runtime: Databricks Apps Python runtime
- App framework: FastAPI + Uvicorn
- RAG backend: Direct Databricks access (SQL Warehouse + Vector Search + Serving)

## Files to upload

Upload only these project files and folders to the Databricks workspace folder:

- `app/`
- `app.yaml`
- `requirements.txt`

Do not upload:

- `.env`
- local PAT tokens
- `__pycache__/`
- `.venv/` or `venv/`
- notebooks
- temporary images, logs, or screenshots

## Required app configuration

`app.yaml` starts the FastAPI app with Uvicorn and uses `DATABRICKS_APP_PORT`.

The app also defines:

- `DATABRICKS_SQL_WAREHOUSE_ID`
- `DIRECT_SQL_TIMEOUT_SECONDS`

Do not set `DATABRICKS_TOKEN` in Databricks Apps. The app uses the Databricks Apps service principal through the Databricks SDK default authentication chain.

## Required permissions

Grant the Databricks App service principal access to:

- Use SQL Warehouse referenced by `DATABRICKS_SQL_WAREHOUSE_ID`.
- Read Unity Catalog tables used by the RAG pipeline.
- Use Vector Search index (`cos_adb.search.metadata_chunks_index` by default).
- Query the Model Serving endpoint (`databricks-qwen3-next-80b-a3b-instruct` by default).
- Read/write audit log tables if production logging is enabled.

For app users:

- Grant `CAN USE` to normal users.
- Grant `CAN MANAGE` only to deployers or operators.

## Deployment steps

1. Confirm local checks pass:
   - `python -m py_compile app/main.py`
   - `python -m uvicorn app.main:app --reload`
   - Open `/`, `/admin-login`, `/admin`, and `/api/health`.

2. Upload app files to a Databricks workspace folder.

3. In Databricks, open **Databricks Apps**.

4. Create or open the target custom app.

5. Select **Deploy** and choose the uploaded workspace folder.

6. After deployment, open the app URL and verify:
   - Common Chat works.
   - Admin login works with `admin/admin`.
   - Admin Chat can query backend directly without Job orchestration delay.
   - SQL Logs show chat source, role, status, and source tables.

7. Check app logs:
   - Databricks Apps **Logs** tab
   - Or append `/logz` to the app URL.

## Validation questions

Common Chat:

- `/chat 안녕`
- `/work 최근 VOC에서 반복적으로 언급된 고객 불만 유형을 요약해줘`

Admin Chat:

- `/work QC 검사 결과에서 OOS 또는 OOT가 발생한 항목을 정리해줘`
- `/work 전체 직원의 급여 요약과 보상 조정 데이터를 보여줘`

## Operational notes

- Current in-app SQL logs are kept in memory and reset when the app restarts.
- For production, connect SQL Logs to a persistent Delta audit table.
- If direct calls fail after deployment, first check app principal permissions for SQL Warehouse, UC tables, Vector Search, and Serving endpoints.
