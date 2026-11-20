# Free deployment: Render + Neon + Resend

This repository includes `render.yaml` for a single, free Render web service. It is suitable for a low-traffic demo or pilot, not a dependable production marketplace: free Render services sleep after 15 minutes without traffic and may take about a minute to wake. Keep application data in Neon, not on Render's disk.

## Accounts to create

1. Create a free Neon Postgres project in the region nearest to the users. Copy its pooled or direct `postgresql://...` connection string. The application normalizes that value to the Psycopg 3 URL form automatically.
2. Create a free Resend account, verify a sending domain, and create an API key. The application sends verification and password-reset messages over HTTPS, which works on Render's free plan.
3. Create a free Render account and connect the Git repository that contains this project.
4. Create a free Render Key Value instance in the same region and copy its Redis-compatible connection string. It is required by this production configuration so rate limits have one shared store instead of resetting per process restart.

## Deploy

1. Change `name` in `render.yaml` to a globally unique service name, then push the repository to GitHub or GitLab.
2. In Render, select **New → Blueprint** and select the repository. Render reads `render.yaml` and creates the free web service.
3. Before the first deploy, set these secret environment variables in Render:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | The Neon connection URL. |
   | `PUBLIC_BASE_URL` | `https://your-service.onrender.com` (or your HTTPS custom domain). |
   | `TRUSTED_HOSTS` | `your-service.onrender.com` (add custom domains separated by commas). |
   | `EMAIL_FROM` | A Resend-verified sender, e.g. `Earn & Pay <noreply@yourdomain.com>`. |
   | `RESEND_API_KEY` | Resend API key. |
   | `RATELIMIT_STORAGE_URI` | Redis-compatible URL from Render Key Value or another managed Redis-compatible service. |

   Render generates `SECRET_KEY` automatically. Do not set the placeholder from `.env.example`.
4. Deploy. The build command installs dependencies and runs `flask db upgrade` before starting Gunicorn. Check `https://your-service.onrender.com/health`; it should return `status: ok`.
5. In a browser, register one Worker and one Employer. Confirm the verification email, sign in, post a test job, apply, and test password reset before sharing the URL.

## Required operational checks

- The filesystem is ephemeral: do not add resumes, images, PDFs, SQLite data, or any other user uploads to `instance/` on the free service. This MVP currently has no upload feature.
- Export the Neon database before schema changes. Render's own free Postgres expires after 30 days and has no backups, which is why this configuration uses Neon instead.
- A free Render service has a single worker here by design. Do not add workers or replicas without keeping `RATELIMIT_STORAGE_URI` shared.
- Rotate `SECRET_KEY`, `RESEND_API_KEY`, and database credentials if they are exposed. Rotating `SECRET_KEY` signs users out, which is expected.
- If Render reports a cold start, wait for `/health` to return OK rather than retrying form submissions.

## Local production smoke check

Use a temporary database and non-production mail backend only for automated tests. For an actual production configuration, all required variables must be present; the app intentionally refuses to start with weak secrets, an in-memory rate limiter, a non-Postgres database, or missing email/host settings.

```powershell
flask --app wsgi:app db upgrade
gunicorn --workers 1 --threads 4 --bind 0.0.0.0:8000 wsgi:app
```

On Windows, use the Flask development server for local testing; Gunicorn runs in Render's Linux environment.
