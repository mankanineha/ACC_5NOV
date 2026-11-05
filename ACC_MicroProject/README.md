# 🚌 Kubernetes-Based Smart Campus Shuttle Seat Booking & Concurrency Management System
> **Course:** Advanced Cloud Computing & DevOps (ACC)  
> **Topic:** High-Concurrency Containerized Seat Allocation, In-Memory Distributed Locking, HPA Autoscaling, and GitOps CI/CD

---

## 📌 Executive Summary

During morning and evening campus rush hours, hundreds of students concurrently attempt to book a limited number of shuttle seats within narrow time windows. Standard monolithic architectures crash under this synchronized demand spike or fail silently through race conditions, causing **double-booked seats**.

This project implements a cloud-native, high-concurrency booking engine inspired by airline reservation and ticketing systems. It features:
- **FastAPI Horizontal Microservices**: Stateless backend pods designed for rapid horizontal scaling.
- **In-Memory Distributed Locking (Redis `SETNX`)**: Provides atomic seat holds and fast rejection (HTTP `409 Conflict` in `<3ms`), completely shielding PostgreSQL from lock contention.
- **ACID Persistence (PostgreSQL with PVC)**: Final booking confirmation with unique database constraints to guarantee zero double-bookings.
- **Kubernetes Horizontal Pod Autoscaling (HPA)**: Dynamically scales backend replicas from **2 to 10 pods** when average CPU exceeds **70%**.
- **Prometheus & Grafana Observability**: Live telemetry for request throughput, response latency, active pod count, and error rates.
- **GitOps CI/CD Pipeline (GitHub Actions)**: Automated linting, pytest concurrency testing, multi-stage Docker builds, and rolling updates.

---

## 🏗️ Architecture & Component Interaction

```text
[ Student Clients / Web UI ]
            │ (HTTP REST)
            ▼
[ NGINX Ingress Controller ]
            │
            ▼ (Round-Robin Load Balancing)
[ FastAPI Application Pods (2 -> 10 Pods via HPA on CPU > 70%) ]
      │                                       │
      ├─ 1. Atomic Hold (SETNX seat_id EX 30s)├─ 2. Confirm Booking (Transactional Write)
      ▼                                       ▼
[ Redis Pod / Cluster ]                 [ PostgreSQL Pod + PVC ]
   ├── Success -> 30s hold                 └── Persists Ticket + Unique Seat Constraint
   └── Conflict -> HTTP 409 (<3ms)
      │                                       │
      └─────────────┬─────────────────────────┘
                    ▼ (Metrics Scraping)
             [ Prometheus Pod ] ────► [ Grafana Dashboards ]
```

---

## 📂 Repository Structure

```text
ACC_MicroProject/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI endpoints, metrics & lifecycle
│   │   ├── database.py          # SQLAlchemy PostgreSQL pool & engine
│   │   ├── redis_client.py      # Redis SETNX atomic lock & Lua scripts
│   │   ├── models.py            # Route, Shuttle, Seat, Booking ORM models
│   │   └── schemas.py           # Pydantic validation schemas
│   ├── tests/
│   │   └── test_booking.py      # Concurrency & double-booking prevention tests
│   ├── Dockerfile               # Multi-stage lightweight Python container
│   └── requirements.txt
├── frontend/
│   ├── index.html               # Visual bus seat selection layout
│   ├── app.js                   # Interactive booking & provisional lock timer
│   ├── style.css                # Dark mode UI with bus schematic layout
│   ├── Dockerfile               # Alpine Nginx container
│   └── nginx.conf
├── k8s/
│   ├── namespace.yaml           # 'campus-shuttle' isolated namespace
│   ├── postgres-pvc.yaml        # Persistent storage claim for database
│   ├── postgres-deployment.yaml # PostgreSQL Stateful Deployment & Service
│   ├── redis-deployment.yaml    # Redis in-memory lock Deployment & Service
│   ├── backend-deployment.yaml  # FastAPI Pods (2 replicas, resource limits)
│   ├── backend-hpa.yaml         # HPA: 2 to 10 pods when CPU > 70%
│   ├── frontend-deployment.yaml # Web UI Deployment & NodePort Service (30080)
│   ├── ingress.yaml             # NGINX Ingress rules
│   └── monitoring/
│       ├── prometheus-k8s.yaml  # Scrapes /metrics on port 8000
│       └── grafana-k8s.yaml     # Pre-configured dashboard on port 30030
├── load_testing/
│   ├── locustfile.py            # 500-user rush hour simulation script
│   └── verify_consistency.py    # Database consistency & zero-double-booking auditor
├── .github/
│   └── workflows/
│       └── ci-cd.yml            # Lint -> Test -> Build & Push -> Deploy
├── docker-compose.yml           # Local test environment
└── README.md
```

---

## ⚡ Concurrency Model: How Double-Booking Is Eliminated

### 1. The Redis `SETNX` Fast Gate
When multiple students attempt to claim Seat #12 at the exact same millisecond:
```python
# Redis command: SET key value EX seconds NX
acquired = await redis.set(f"lock:seat:{seat_id}", student_id, ex=30, nx=True)
```
- **The First Student**: Receives `True`. The seat is locked for 30 seconds with a countdown timer.
- **The Other 499 Students**: Receive `False`. The request is rejected instantly with `HTTP 409 Conflict` in `<3ms`.
- **Benefit**: The PostgreSQL database is never touched by the 499 failing requests, preventing connection pool exhaustion and database CPU spikes.

### 2. Atomic Release via Lua Script
To ensure Student A cannot accidentally release Student B's lock:
```lua
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
```

### 3. Database Layer Safety
Even if the distributed locking layer is bypassed, PostgreSQL enforces a database-level unique constraint on `seat_id` in the `bookings` table:
```python
__table_args__ = (
    UniqueConstraint("seat_id", name="uq_seat_active_booking"),
)
```
Any race condition at the database level results in an `IntegrityError` rollback, mathematically guaranteeing zero double-bookings.

---

## 🚀 Running the Project

### Option A: Deploying to Kubernetes (Minikube / Docker Desktop / Kind)

#### 1. Start your Kubernetes Cluster
```bash
# For Minikube:
minikube start --cpus=4 --memory=4096

# Enable metrics-server (required for HPA):
minikube addons enable metrics-server
minikube addons enable ingress
```

#### 2. Build Container Images in Kubernetes Docker Environment
```bash
# Point your terminal to Minikube's Docker daemon
eval $(minikube docker-env)

# Build images
docker build -t shuttle-backend:latest ./backend
docker build -t shuttle-frontend:latest ./frontend
```

#### 3. Apply Kubernetes Manifests
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/postgres-pvc.yaml
kubectl apply -f k8s/postgres-deployment.yaml
kubectl apply -f k8s/redis-deployment.yaml
kubectl apply -f k8s/backend-deployment.yaml
kubectl apply -f k8s/backend-hpa.yaml
kubectl apply -f k8s/frontend-deployment.yaml
kubectl apply -f k8s/monitoring/prometheus-k8s.yaml
kubectl apply -f k8s/monitoring/grafana-k8s.yaml
```

#### 4. Access the Applications
- **Web UI**: Open `http://localhost:30080` (or `minikube service frontend-service -n campus-shuttle`)
- **Prometheus**: `http://localhost:30090`
- **Grafana**: `http://localhost:30030`
- **Backend API & Docs**: `http://localhost:8000/docs` (via port-forward: `kubectl port-forward svc/backend-service 8000:8000 -n campus-shuttle`)

---

### Option B: Quick Local Testing with Docker Compose
```bash
docker compose up --build
```
- Web UI: `http://localhost:8080`
- API Docs: `http://localhost:8000/docs`

---

## 🧪 Live Demonstration Guide (For Presentation & Viva)

### Step 1: Normal Booking Demo
1. Open the Web UI in your browser.
2. Observe the current serving Pod name displayed in the top right badge (demonstrating load balancing).
3. Select Seat `1A` and click **"Hold Selected Seat (30s)"**.
4. Observe the real-time countdown progress bar.
5. Click **"Confirm Booking"** to receive the Boarding Pass ticket.

### Step 2: Concurrency & Rush Hour Load Test
Open two terminal windows:

**Terminal 1 — Watch HPA scaling in real time:**
```bash
kubectl get hpa backend-hpa -n campus-shuttle -w
```

**Terminal 2 — Launch 500 concurrent students:**
```bash
# Install locust if needed: pip install locust requests
cd load_testing
locust -f locustfile.py --headless -u 500 -r 50 -t 60s --host http://localhost:8000
```

### Step 3: Verify Zero Double-Bookings (The Proof)
Run the automated consistency verification script:
```bash
python load_testing/verify_consistency.py http://localhost:8000
```

**Expected Output:**
```text
=================================================================
  KUBERNETES SHUTTLE SYSTEM: POST-LOAD INTEGRITY AUDIT
=================================================================
[OK] Service Health: UP (Pod: backend-deployment-78bf664b9-x2w9k)
[INFO] Total Confirmed Bookings in Database: 24
-----------------------------------------------------------------
  AUDIT CHECKS:
  [PASS] Zero Double-Bookings Detected!
         Every confirmed seat belongs to exactly ONE student.
  [PASS] Database State: 24 / 24 seats reserved.
-----------------------------------------------------------------
  CONCLUSION: CONCURRENCY CONTROLS VALIDATED UNDER LOAD.
  - Redis SETNX Distributed Lock: Effective
  - PostgreSQL Row-Level Transaction: Consistent
=================================================================
```

---

## 🎯 Viva / Exam Defense Questions & Answers

**Q1: Why use Redis for locking instead of just handling it in PostgreSQL?**  
> *Answer:* PostgreSQL uses disk-backed row locking which creates heavy connection pool queuing, high latency, and deadlocks when hundreds of requests arrive in the same second. Redis operations (`SETNX`) are executed entirely in-memory in single-threaded microsecond time, rejecting 99% of conflicting requests before they ever touch the database.

**Q2: What happens if a student's browser crashes after locking a seat?**  
> *Answer:* The lock has an explicit 30-second TTL (`EX 30`). Redis automatically evicts the lock key when the timer expires, making the seat available again with zero manual cleanup.

**Q3: How does the HPA decide when to scale up?**  
> *Answer:* The Kubernetes `metrics-server` continuously scrapes CPU consumption from the pod cgroups. When the average CPU utilization across backend pods exceeds 70% of the requested limit (100m), HPA adds replicas up to the configured limit of 10 pods.

**Q4: How does your CI/CD pipeline ensure zero downtime during rollouts?**  
> *Answer:* The Kubernetes Deployment specifies `RollingUpdate` with `maxSurge: 1` and `maxUnavailable: 0`. Kubernetes spins up a new pod and waits for its readiness probe (`/api/health`) to pass before routing traffic to it and terminating old pods.
