from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.db import init_db
from app.api.routes import router as routes_router
from app.api.webhooks import router as webhooks_router
from app.audit.logger import AuditLogger
from app.execution.simulator import SubscriptionSimulator
from app.pipeline import RecoveryPipeline
from app.models.calibrated_tlearner import CalibratedTLearner
from app.config import MODEL_DIR, BASE_DIR, MODEL_VERSION

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    model=None
    path=MODEL_DIR/'calibrated_tlearner.joblib'
    if path.exists():
        try:
            model=CalibratedTLearner(MODEL_DIR); model.load()
        except Exception as exc:
            print(f'Model load failed; using simulator fallback: {exc}')
    audit=AuditLogger()
    app.state.audit=audit
    app.state.pipeline=RecoveryPipeline(model=model, simulator=SubscriptionSimulator(), audit=audit)
    yield

app=FastAPI(title='REVIVE 6.0', description='Risk-aware incremental revenue recovery for Razorpay subscriptions', version='6.0', lifespan=lifespan)
app.include_router(routes_router)
app.include_router(webhooks_router)
frontend=BASE_DIR/'frontend'
if frontend.exists(): app.mount('/static', StaticFiles(directory=frontend), name='static')
