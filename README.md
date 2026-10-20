# CloudBus Pass — Cloud-Based Bus Pass / Ticket Booking System

A ready-to-run Flask project demonstrating route search, account registration/login, seat booking, server-side fare calculation, ticket reference storage, and booking history. Includes Docker packaging and a health endpoint.

## Features
- Search scheduled routes by origin, destination, and date.
- Register and sign in; password hashes use PBKDF2-HMAC-SHA256.
- Reserve 1–6 seats with a database transaction to reduce overselling during concurrent bookings.
- Fare comes from the server-side route record, not a submitted browser price.
- Unique booking reference and ticket page; bookings are associated with the signed-in account.
- Booking history and `/health` endpoint for monitoring.
- Dockerfile, Docker Compose, Gunicorn, and tests.

## Run locally (Python 3.10+)
```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```
Set a strong secret before running. Windows PowerShell:
```powershell
$env:SECRET_KEY="replace-with-a-long-random-secret"
python app.py
```
macOS/Linux:
```bash
export SECRET_KEY="replace-with-a-long-random-secret"
python app.py
```
Open http://127.0.0.1:5000

## Run with Docker
Install Docker Desktop, then from this folder:
```bash
docker compose up --build
```
Open http://localhost:5000. The database is stored in the persistent `busdata` volume.

## Run tests
```bash
python -m unittest discover -s tests -v
```

## Deploy / cloud scaling notes
- The included container can run on AWS ECS/Fargate, Azure Container Apps, Google Cloud Run, or Kubernetes.
- Configure at least 2 app replicas behind a managed HTTPS load balancer for availability.
- Set `SECRET_KEY` using the cloud provider's secret manager. Never use the development fallback in production.
- **Important for horizontal scaling:** SQLite is suitable for a demo or single-instance deployment, not a multi-replica production deployment. For production, replace SQLite with PostgreSQL (for example Amazon RDS/Aurora), use a shared managed database, and configure connection pooling and transaction isolation. Put ticket PDFs/QR images in object storage if added.
- Enable autoscaling based on CPU, request count, or latency; set minimum and maximum replica counts and health check path `/health`.
- Use HTTPS, rate limiting, CSRF protection, monitoring/alerts, backups, and payment-provider webhooks before handling real customer data or payments.

## Requirements mapping
| Requirement | Implementation |
|---|---|
| Online booking | Route search, registration, booking, ticket and booking history |
| Prevent ticket loss | Ticket reference and booking history stored in database |
| Prevent theft | Authenticated ticket access; users only see their own tickets |
| Prevent incorrect pricing | Server-side fare lookup; browser-supplied price ignored |
| High traffic | Container + Gunicorn; cloud deployment/autoscaling guidance |
| Scalability and reliability | Health endpoint, persistent data volume, transaction-safe seat reservation; production scaling architecture documented |

## Demo limitations
This is a complete runnable academic/demo project, not a production ticketing/payment platform. It does not charge money, issue operator-valid tickets, send SMS/email, or include a real cloud autoscaler configuration. The default sample routes are inserted automatically. For a production deployment, use managed PostgreSQL and the cloud platform's autoscaling controls.
