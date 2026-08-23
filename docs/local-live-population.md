# Populate the live database with local Ollama

## Use the guarded loader

`backend/populate_live.py` scrapes recent official ASX documents. It sends the
document text to local Ollama, then writes the result to PostgreSQL.

The loader has these limits:

- Dry-run is the default.
- A live write needs `--execute` and an exact `--confirm-host` value.
- Local database hosts are rejected in live mode.
- The default cap is three new documents per ticker from the last 30 days.
- Existing source document identities are skipped.
- The loader does not run migrations, delete rows, or replace old results.
- Ollama must use a local endpoint. Remote model hosts are rejected.
- Model, prompt, provider, and publication state are saved in artifact metadata.

Run each command from the `backend` folder. On this Windows checkout, use a
writable `UV_CACHE_DIR`:

```powershell
$env:UV_CACHE_DIR = 'C:\Users\Arv\AppData\Local\Temp\stocks-in-hand-uv-cache'
uv run --no-project --with-requirements requirements-local-populate.txt `
  python populate_live.py --lookback-days 30 --max-documents 3
```

This discovers documents only. It does not call Ollama or connect to a database.

## Confirm the live target

Take a restorable Supabase backup before the first write. Use the migration or
session-pooler PostgreSQL URL. Do not add it to `backend/.env`.

If AWS access is configured, load the existing SSM value without printing it:

```powershell
$env:LIVE_DATABASE_URL = aws ssm get-parameter `
  --name '/stocks-in-hand/staging/database-url' `
  --with-decryption `
  --query 'Parameter.Value' `
  --output text
```

Otherwise, enter the Supabase URL with masked input:

```powershell
$env:LIVE_DATABASE_URL = Read-Host 'Supabase PostgreSQL URL' -MaskInput
```

Ask the loader for the expected hostname. This stops before connecting or
writing because the confirmation is missing:

```powershell
uv run --no-project --with-requirements requirements-local-populate.txt `
  python populate_live.py --execute --tickers CSL --max-documents 1
```

The error gives the exact `--confirm-host` value. Check it against Supabase or
the approved SSM parameter before continuing.

## Load one document first

Replace `<confirmed-host>` with the exact checked hostname:

```powershell
uv run --no-project --with-requirements requirements-local-populate.txt `
  python populate_live.py `
  --execute `
  --confirm-host '<confirmed-host>' `
  --tickers CSL `
  --lookback-days 30 `
  --max-documents 1 `
  --model 'qwen3.5:latest'
```

The final JSON reports the scrape run status and verified artifact, summary,
and sentiment counts. Check that run before increasing the scope.

## Load the supported set

After the one-document check passes:

```powershell
uv run --no-project --with-requirements requirements-local-populate.txt `
  python populate_live.py `
  --execute `
  --confirm-host '<confirmed-host>' `
  --lookback-days 30 `
  --max-documents 3 `
  --model 'qwen3.5:latest'
```

Remove the URL from the process environment when finished:

```powershell
Remove-Item Env:LIVE_DATABASE_URL
```

The current BHP scraper may return no rows. Treat zero BHP records as a source
failure to fix, not proof that BHP had no announcements.
