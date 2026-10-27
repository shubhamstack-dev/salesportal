# Sales portal

Field sales, attendance and expenses for Samurai Foods, connected to Microsoft Dynamics.

- **React** frontend (Vite), used on phones by sales staff and on desktops by the office
- **Python** middleware: a FastAPI REST API that holds every business rule
- **MySQL 8** database shared by everyone

```
sales-portal/
├── backend/
│   ├── app/
│   │   ├── main.py              app, CORS, table creation
│   │   ├── db.py                settings: database, JWT, time zone
│   │   ├── models.py            20 tables
│   │   ├── security.py          bcrypt, JWT, roles, who sees whose data, who approves
│   │   ├── services/
│   │   │   ├── calc.py          pricing, GST, charges, outstanding, expense and attendance rules
│   │   │   ├── dynamics.py      Dynamics download, export, acknowledgement, API (with Entra ID token)
│   │   │   ├── common.py        settings, local time, document numbers, sync log
│   │   │   └── xl.py            Excel downloads
│   │   └── routers/             auth, org (employees, grades, settings), masters, sales (quotations,
│   │                            orders, payments), expenses, attendance, dashboard, integration
│   └── tests/test_portal.py     API tests (SQLite or MySQL) + Sample_Dynamics_Masters.xlsx
├── frontend/src/                App.jsx (menu, roles, routing), lib.js, maps.jsx, ui.jsx, pages/
├── database/schema.sql          MySQL schema (optional; the API creates missing tables)
├── docker-compose.yml, .env.example
```

## What it does

| Area | Who | What |
|---|---|---|
| Time in / Time out | everyone | Punch with GPS location, note and street address; history; late, half-day and short days against the shift; correction requests approved by the manager |
| Attendance | managers | Monthly muster (P, H, S, A, WO, late), day detail with map, Excel download |
| Quotations | everyone | Priced from Dynamics price lists, GST from HSN, charges; sent to Dynamics as sales quotes; convert to an order |
| Sales orders | everyone | Approval by a manager, credit-limit check, location and distance from the customer |
| Payments | everyone | Cash, cheque, UPI, NEFT, card; allocation to open orders; printable receipt |
| Expenses | everyone | Claims against the employee's grade: fixed daily allowance, variable rate per km, hotel defaulted per night; approval |
| Expense policy | admin | Grades with in-station and out-station rates |
| Masters | read-only | Customers, materials with attributes, prices, HSN/GST, charges: downloaded from Dynamics only |
| Dynamics sync | admin | Masters in (file or API), transactions out (file or API), document numbers back |
| Dashboard | managers | Who is on duty, live locations, orders, collections, approvals waiting |

**Rules are worked out on the server**, never trusted from the phone: prices (customer price, then price group, then base price, by dates and minimum quantity), GST (CGST + SGST in the company's state, IGST elsewhere), charges before and after GST, round-off, credit limits, expense amounts, attendance status. The browser shows the server's preview while you type.

**Roles.** Sales representatives see their own customers (an assigned list, or all), documents, claims and attendance. Sales managers see their team (everyone, if no one reports to them) and approve orders, expense claims and attendance corrections. Administrators see everything, maintain employees, grades and settings, and run the Dynamics sync. Nobody approves their own claim or correction, except a sole administrator.

## Quick start (Docker)

```bash
cp .env.example .env          # change the passwords and JWT_SECRET
docker compose up -d --build
```

Open http://localhost:8080 and create the administrator. Then:

1. **Dynamics sync** → import customers, materials, attributes, prices, HSN codes and charges. `backend/tests/Sample_Dynamics_Masters.xlsx` shows the layout (Business Central export column names are recognised automatically, and columns can be re-mapped on the preview).
2. **Expense policy** → add grades.
3. **Employees and users** → add staff with role, grade, manager and (for reps) customers.
4. **Settings** → company GSTIN and state, shift timings, Google Maps key.

Phones share their location only over **https**: put the portal behind a reverse proxy with a certificate (nginx, Caddy, or your load balancer).

## Running without Docker

```bash
# MySQL
CREATE DATABASE sales_portal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'sales'@'%' IDENTIFIED BY 'a-strong-password'; GRANT ALL ON sales_portal.* TO 'sales'@'%';

# backend
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
export DATABASE_URL="mysql+pymysql://sales:a-strong-password@localhost:3306/sales_portal?charset=utf8mb4"
export JWT_SECRET="long-random-string" APP_TZ="Asia/Kolkata"
uvicorn app.main:app --port 8000          # API docs at http://localhost:8000/docs

# frontend
cd frontend && npm install && npm run dev  # http://localhost:5173, forwards /api to port 8000
npm run build                              # production files in dist/, serve with nginx.conf
```

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `mysql+pymysql://sales:sales@localhost:3306/sales_portal?charset=utf8mb4` | Database |
| `JWT_SECRET` | `change-this-secret` | Signs sign-in tokens. **Change it.** |
| `JWT_HOURS` | `8` | Length of a sign-in |
| `APP_TZ` | `Asia/Kolkata` | Local time for attendance, shifts and document dates |
| `CORS_ORIGINS` | `http://localhost:5173` | Frontend addresses allowed to call the API |
| `IMPORT_DIR` | system temp folder | Where uploaded files wait between preview and Apply |

## Microsoft Dynamics

**Masters in.** Excel/CSV exported from Dynamics, or the API. Records are matched by their Dynamics number; prices and charges are replaced as a whole. No screen or endpoint creates or changes master data.

**Transactions out.**
- *File*: one workbook with Quote Header/Lines, Sales Header/Lines, Order Charges, Payments (cash receipt journal; amounts negative by default) and Employee Expenses (journal lines DA, TRAVEL, HOTEL, OTHER, account type Employee). Items are then "Sent by file" until the **acknowledgement** is imported: a list with *External Document No.* (portal number) and *Document No.* (Dynamics number).
- *API*: posts to the endpoints set under Dynamics connection (Business Central `salesQuotes` and `salesOrders` with lines, `customerPaymentJournals(...)/customerPayments`, and a custom endpoint for expenses). The numbers Dynamics returns are stored straight away.

**Authentication.** The server calls Dynamics itself, so browser CORS rules do not apply. Register an app in Microsoft Entra ID with access to the Dynamics API, and enter the tenant id, client id and secret; the server fetches tokens with the client-credentials flow. A pasted token also works for testing.

The standard Business Central API has customers, items, sales quotes, sales orders and customer payments, but not price lists, charges, HSN codes, GSTIN or employee expenses: download those by file, or ask your Dynamics partner for custom API pages and enter their endpoints.

## Tests

```bash
cd backend
pytest -q                                   # SQLite
TEST_DATABASE_URL="mysql+pymysql://user:pass@localhost:3306/sales_test?charset=utf8mb4" pytest -q
```

They cover: master download from the sample workbook and that masters cannot be written; Time In/Out with the location rule; late, short and corrected days and the approval of a correction; quotation pricing (customer, group and quantity breaks), conversion to an order, freight and GST (CGST/SGST and IGST), approval rights; payments with allocation limits; expense claims with hotel defaults, overage, overlapping dates and approval; that reps see only their own data; and the full Dynamics round trip.

## Before going live

- Set a long random `JWT_SECRET` and strong database passwords; serve over HTTPS.
- Restrict the Google Maps key to the portal's address (Maps JavaScript API and Geocoding API).
- Back up MySQL daily (`mysqldump sales_portal`). Client secrets for Dynamics are stored in the database: restrict access to it.
- `create_all` only adds missing tables; use a migration tool (Alembic) for later changes to existing tables.
