# Earn & Pay

**Local Employment & Temporary-Work Marketplace MVP**  
*Find Work. Earn Money. Build Your Future.*

Earn & Pay connects people seeking part-time, temporary, and daily-wage work with local employers (shops, restaurants, small businesses, and service providers) through a transparent, accessible, server-rendered web marketplace.

---

## Technology Stack

- **Frontend:** HTML5, CSS3 (Editorial Design System Tokens), Vanilla JavaScript, Jinja2
- **Backend:** Python 3.12+, Flask (Application Factory + Modular Blueprints)
- **Database & ORM:** PostgreSQL 18, SQLAlchemy 2.0, Psycopg 3, Flask-Migrate (Alembic)
- **Security & Auth:** Flask-Login, Flask-WTF (CSRF), Werkzeug password hashing, Flask-Limiter
- **Quality & Testing:** pytest, Ruff

---

## Quick Start (Local Development)

### 1. Create and Activate Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and update your local PostgreSQL credentials:

```powershell
Copy-Item .env.example .env
```

### 3. Provision Local PostgreSQL Databases

```sql
CREATE DATABASE earn_and_pay_dev ENCODING 'UTF8';
CREATE DATABASE earn_and_pay_test ENCODING 'UTF8';
```

### 4. Verify Database Connectivity & Run Tests

```powershell
flask db-check
ruff check .
pytest
```
